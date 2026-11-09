import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extract import combine_candidates,ssa_candidates,broker_candidates,reference_candidates
from review import checks

def w(text,x,y,width=.025):return {'text':text,'box':[x,y,width,.01],'confidence':90}
def record(number,form,values,role='source',**extra):
 return dict(id=number,page_id=number,document_id=1,form_type=form,values=values,role=role,status='reviewed',
             disposition='included',owner='taxpayer',payer='',account_alias='',**extra)

class ReviewTests(unittest.TestCase):
 def test_ssa_grid_and_explicit_none(self):
  words=[]
  for number,x in [(3,.05),(4,.36),(5,.68)]:words += [w('Box',x,.5),w(str(number)+'.',x+.04,.5)]
  words += [w('$100.50',.13,.53,.08),w('NONE',.45,.53,.07),w('$100.50',.78,.53,.08)]
  result=ssa_candidates(words)
  self.assertEqual(result['benefits_paid']['value'],'100.50');self.assertEqual(result['benefits_repaid']['value'],'0.00')
  self.assertEqual(result['net_benefits']['box'],words[-1]['box'])
 def test_broker_column_guard(self):
  words=[w('SCHWAB',.05,.1),w('Total',.05,.5),w('Short-Term',.10,.5,.06),w('(Cost',.18,.5),
         w('basis',.23,.5),w('is',.27,.5),w('reported',.30,.5),w('100.00',.52,.5,.05),w('110.00',.63,.5,.05),w('5.00',.88,.5,.04)]
  self.assertEqual(broker_candidates(words),{})
  words[-1]=w('5.00',.72,.5,.04)
  self.assertEqual(broker_candidates(words)['wash_sale_disallowed']['value'],'5.00')
 def test_reference_cells_and_conflict(self):
  words=[w('1a',.81,.4),w('100.',.91,.4,.05)]
  self.assertEqual(reference_candidates(words)['wages']['value'],'100.00')
  self.assertEqual(combine_candidates({'wages':{'value':'100.00'}},{'wages':{'value':'110.00'}}),{})
 def test_pending_page_blocks_match(self):
  rs=[record(1,'W-2',{'wages':'100.50'}),record(2,'1040-reference',{'wages':'101.00'},role='reference')]
  docs=[{'id':1,'role':'source','status':'done'}]
  ps=[{'id':1,'page_number':1,'role':'source','disposition':'pending'}]
  result=checks(rs,ps,docs);self.assertEqual(result['comparisons'][0]['status'],'incomplete')
  ps[0]['disposition']='included'
  self.assertEqual(checks(rs,ps,docs)['comparisons'][0]['status'],'match')
  rs.append(record(3,'1040-reference',{'wages':'102.00'},role='reference'))
  self.assertEqual(checks(rs,ps,docs)['comparisons'][0]['status'],'reference_conflict')
 def test_equations_and_mixed_levels(self):
  rs=[record(1,'SSA-1099',{'benefits_paid':'100','benefits_repaid':'10','net_benefits':'100'}),
      record(2,'1099-B',{'proceeds':'100','cost_basis':'110','wash_sale_disallowed':'5','reported_gain':'-5'},entry_level='summary'),
      record(3,'1099-B',{},entry_level='detail')]
  issues=checks(rs,[],[])['issues']
  self.assertTrue(any('SSA-1099' in i['message'] for i in issues if i['severity']=='error'))
  self.assertTrue(any('同时保留' in i['message'] for i in issues))
  self.assertFalse(any('证券收益与' in i['message'] for i in issues))
  rs[1]['category']='A';rs[2]['category']='D'
  self.assertFalse(any('同时保留' in i['message'] for i in checks(rs,[],[])['issues']))
 def test_amount_alone_is_not_duplicate(self):
  rs=[record(1,'W-2',{'wages':'100'}),record(2,'W-2',{'wages':'100'})]
  self.assertFalse(any('可能重复' in i['message'] for i in checks(rs,[],[])['issues']))
  for r in rs:r.update(payer='Company',account_alias='Account A')
  self.assertTrue(any('可能重复' in i['message'] for i in checks(rs,[],[])['issues']))
if __name__=='__main__':unittest.main()
