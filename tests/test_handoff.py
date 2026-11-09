import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from handoff import build_handoff

class HandoffTests(unittest.TestCase):
    def build(self, records=None, pages=None, docs=None, report=None):
        return build_handoff(records or [], pages or [], docs or [], report or {'issues':[], 'comparisons':[]})
    def test_empty_is_not_complete(self):
        h=self.build()
        self.assertEqual(h['tasks'][0]['kind'],'upload')
        self.assertFalse(h['filing_ready'])
        self.assertEqual(h['page_progress_percent'],0)
    def test_reviewed_record_does_not_complete_pending_page(self):
        p={'id':1,'document_id':1,'page_number':1,'disposition':'pending'}
        r={'id':2,'page_id':1,'form_type':'W-2','status':'reviewed'}
        h=self.build([r],[p],[{'id':1,'status':'done','page_count':1}])
        self.assertEqual(h['task_counts'],{'page':1})
        self.assertEqual(h['tasks'][0]['page_id'],1)
    def test_included_empty_page_and_missing_pages(self):
        p={'id':1,'document_id':1,'page_number':1,'disposition':'included'}
        h=self.build(pages=[p],docs=[{'id':1,'status':'done','page_count':2}])
        self.assertEqual(h['task_counts'],{'missing_pages':1,'empty_page':1})
    def test_excluded_page_not_record_task(self):
        p={'id':1,'document_id':1,'page_number':1,'disposition':'excluded','error':'bad'}
        r={'id':2,'page_id':1,'form_type':'W-2','status':'pending'}
        h=self.build([r],[p],[{'id':1,'status':'done','page_count':1}])
        self.assertEqual(h['status'],'uploaded_review_complete')
        self.assertFalse(h['filing_ready'])
        self.assertEqual(h['page_progress_percent'],100)
    def test_conflicts_preserved_and_todos_not_duplicated(self):
        report={'issues':[{'severity':'todo','message':'pending'},{'severity':'error','message':'duplicate mix','record_id':5,'page_id':3}], 'comparisons':[{'status':'difference','label':'wages','source_total':'100','reference':'200'}]}
        h=self.build(docs=[{'id':1,'status':'processing'}],report=report)
        self.assertEqual(h['task_count'],3)
        self.assertEqual(h['tasks'][1]['record_id'],5)
        self.assertEqual(h['task_counts']['comparison'],1)
