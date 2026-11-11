import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extract import w2_candidates


def word(text,x,y,width=.015):
    return {'text':text,'box':[x,y,width,.008],'confidence':90}


def label(text,x,y):
    return [word(token,x+i*.022,y) for i,token in enumerate(text.split())]


def copy_words(dx=0,dy=0,amount_y=.365,wages='100.00',withheld='5.00'):
    words=[]
    for text,x,y in [('Wages tips other comp',.16,.10),
                     ('Federal income tax withheld',.32,.10),
                     ('15 State',.05,.40),('16 State wages',.24,.40),
                     ('17 State income tax',.36,.40),('18 Local wages',.05,.46)]:
        words.extend(label(text,x+dx,y+dy))
    words.extend([word('100.00',.20+dx,.12+dy,.05),word('5.00',.40+dx,.12+dy,.05),
                  word(wages,.28+dx,amount_y+dy,.05),word(withheld,.40+dx,amount_y+dy,.05)])
    return words


class W2StateTests(unittest.TestCase):
    def test_captions_above_or_below_values_with_evidence(self):
        for y in [.365,.425]:
            with self.subTest(amount_y=y):
                result=w2_candidates(copy_words(amount_y=y))
                self.assertEqual(result['state_wages']['value'],'100.00')
                self.assertEqual(result['state_withheld']['value'],'5.00')
                self.assertEqual(result['state_wages']['box'],[.28,y,.05,.008])

    def test_copies_do_not_merge(self):
        words=copy_words()+copy_words(dx=.49,wages='999.00')+copy_words(dy=.49,wages='888.00')
        self.assertEqual(w2_candidates(words)['state_wages']['value'],'100.00')

    def test_multiple_state_rows_remain_blank(self):
        words=copy_words()+[word('100.00',.28,.385,.05),word('5.00',.40,.385,.05)]
        result=w2_candidates(words)
        self.assertNotIn('state_wages',result)
        self.assertNotIn('state_withheld',result)

    def test_missing_state_value_does_not_use_local_or_other_copy(self):
        words=copy_words()
        words=[w for w in words if not (w['text']=='100.00' and w['box'][1]==.365)]
        words += [word('777.00',.28,.48,.05)] + copy_words(dx=.49,wages='999.00')
        self.assertNotIn('state_wages',w2_candidates(words))
        self.assertEqual(w2_candidates(words)['state_withheld']['value'],'5.00')


if __name__=='__main__':unittest.main()
