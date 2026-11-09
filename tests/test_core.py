import csv
import io
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import OCR_SEPARATOR,aligned_ocr_text,classify,export_rows,money,suggestions,validate_record

class CoreTests(unittest.TestCase):
    def test_money_keeps_missing_and_cents(self):
        self.assertIsNone(money(''))
        self.assertIsNone(money(None))
        self.assertEqual(money('$33,821.75'),'33821.75')
        self.assertEqual(money('(121.00)'),'-121.00')
        self.assertEqual(money('0'),'0.00')
        for invalid in ['1.234','NaN','Infinity','1e4','=SUM(A1)', 'abc']:
            with self.assertRaises(ValueError):money(invalid)
    def test_no_income_from_authorization_or_estimates(self):
        for text in ['IRS e-file Signature Authorization Form 8879 1099-B',
                     '2026 PAYMENT VOUCHER 1099-DIV',
                     'YEAR-END SUMMARY FORM 1099 COMPOSITE 1099-B',
                     'SUPPLEMENTAL INFORMATION 1099-DIV',
                     'INSTRUCTIONS FOR RECIPIENT FORM 1099-B']:
            self.assertEqual(classify(text),[])
    def test_multiple_forms_and_ssa(self):
        self.assertEqual(classify('Form 1099-DIV Ordinary Dividends Form 1099-INT Interest Income'),['1099-INT','1099-DIV'])
        self.assertEqual(classify('SSA-1099 SOCIAL SECURITY BENEFIT STATEMENT Box 5'),['SSA-1099'])
        self.assertEqual(classify('Form   1040   U.S. Individual Income Tax Return', 'reference'),['1040-reference'])
        self.assertEqual(classify('D-400 Individual Income Tax Return 1a 24', 'reference'),[])
        self.assertEqual(classify('1099-B Proceeds from Broker Transactions Please see Notes for Your Form 1099-B'),['1099-B'])
    def test_suggestions_refuse_ambiguous_values(self):
        self.assertEqual(suggestions('1a Total Ordinary Dividends 3,627.29','1099-DIV')['ordinary_dividends']['value'],'3627.29')
        self.assertEqual(suggestions('1a Total Ordinary Dividends 3,627.29 0.00','1099-DIV'),{})
        self.assertEqual(suggestions('1a Total Ordinary Dividends 3,627.29\n1a Total Ordinary Dividends 3,627.29','1099-DIV'),{})
        self.assertEqual(suggestions('1a Total Ordinary Dividends\n3,627.29','1099-DIV'),{})
    def test_review_gate(self):
        base={'form_type':'W-2','owner':'spouse','status':'reviewed','reviewer':'EMP01',
              'confirmed_blanks':True,'values':{'wages':'52845.48'}}
        result=validate_record(base)
        self.assertEqual(result['values']['wages'],'52845.48')
        self.assertIsNone(result['values']['ss_wages'])
        for update in [{'reviewer':''},{'owner':'unknown'},{'owner':'joint'},{'confirmed_blanks':False},{'values':{}}]:
            with self.assertRaises(ValueError):validate_record({**base,**update})
        with self.assertRaises(ValueError):validate_record({**base,'values':{'unknown':'1'}})
    def test_1099b_category_required(self):
        with self.assertRaises(ValueError):validate_record({'form_type':'1099-B','owner':'joint','status':'reviewed',
           'reviewer':'EMP01','confirmed_blanks':True,'values':{'proceeds':'165644.24'}})
    def test_csv_formula_guard_preserves_negative_amount(self):
        rec=dict(tax_year=2025,client_id=1,filename='=HYPERLINK(1)',page_number=1,id=1,form_type='1099-B',
                 owner='joint',payer='+formula',values={'adjustment_amount':'-1.00'},reviewer='@a')
        rows=list(csv.reader(io.StringIO(export_rows([rec]))))
        self.assertTrue(rows[1][2].startswith("'="))
        self.assertEqual(rows[1][11],'-1.00')
    def test_visual_rows_join_across_ocr_blocks(self):
        tsv='level\tleft\ttop\theight\ttext\n5\t10\t100\t20\tDividends\n5\t500\t101\t18\t3,627.29\n5\t10\t150\t20\tInterest\n'
        self.assertEqual(aligned_ocr_text(tsv),'Dividends 3,627.29\nInterest')
    def test_conflicting_ocr_views_are_not_suggested(self):
        self.assertEqual(suggestions('1a Total Ordinary Dividends 27.25'+OCR_SEPARATOR+'1a Total Ordinary Dividends 21.25','1099-DIV'),{})

if __name__=='__main__':unittest.main()
