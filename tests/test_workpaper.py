import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from taxtracker.verification.workpaper import render_workpaper

class WorkpaperTests(unittest.TestCase):
 def data(self):
  record={'id':1,'form_type':'1099-DIV','owner':'taxpayer','values':{'ordinary_dividends':'12.34'},'status':'reviewed','disposition':'included','filename':'<img src=x onerror=alert(1)>.pdf','page_number':2,'notes':'<script>bad()</script>','reviewer':'EMP01'}
  return {'client':{'alias':'<script>unsafe</script>','tax_year':2025},'generated_at':'test','warnings':[],'review_checks':{'issues':[],'notice':'Limited comparison'},'records':[record],'reference_records':[]}
 def test_escapes_user_content_and_preserves_cents(self):
  html=render_workpaper(self.data());self.assertNotIn('<script>',html);self.assertNotIn('<img src=x',html)
  self.assertIn('&lt;script&gt;',html);self.assertIn('12.34',html);self.assertIn('未填写',html)
 def test_reviewed_scope_requires_page_confirmation(self):
  data=self.data();data['records'][0]['disposition']='pending'
  self.assertNotIn('<h3>#1',render_workpaper(data));self.assertIn('<h3>#1',render_workpaper(data,'draft'))
 def test_errors_block_reviewed_but_allow_draft(self):
  data=self.data();data['review_checks']['issues']=[{'severity':'error','message':'Mismatch'}]
  with self.assertRaises(ValueError):render_workpaper(data)
  self.assertIn('Mismatch',render_workpaper(data,'draft'))
if __name__=='__main__':unittest.main()
