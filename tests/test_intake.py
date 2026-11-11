import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from taxtracker.clients.intake import validate_item,reminder
from taxtracker.verification.handoff import build_handoff

class IntakeTests(unittest.TestCase):
    def item(self,**kw):return dict(label='W-2 <test>',owner='taxpayer',state='missing',notes='',reviewer='QA',**kw)
    def test_validation(self):
        self.assertIsNone(validate_item(self.item())['document_id'])
        for key,value in [('label',''),('owner','return'),('state','bad'),('reviewer',''),('state','not_applicable')]:
            data=self.item();data[key]=value
            with self.assertRaises(ValueError):validate_item(data)
        data=self.item(document_id=1)
        with self.assertRaises(ValueError):validate_item(data)
    def test_reminder_only_missing_and_no_internal_notes(self):
        a=self.item();a['notes']='INTERNAL'
        b=self.item();b['state']='received';b['label']='ALREADY'
        t=reminder({'alias':'demo','tax_year':2025},[a,b])
        self.assertIn('W-2 <test>',t);self.assertNotIn('ALREADY',t);self.assertNotIn('INTERNAL',t)
    def test_missing_reaches_handoff(self):
        h=build_handoff([],[],[],{'issues':[],'comparisons':[]},[self.item()])
        self.assertEqual(h['task_counts']['missing_document'],1)
        self.assertFalse(h['filing_ready'])
