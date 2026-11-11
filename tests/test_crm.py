import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from taxtracker.runtime import app
from taxtracker.clients import crm
from taxtracker.operations import restore_backup


class CRMTests(unittest.TestCase):
    def test_year_delete_restore_keeps_other_year_and_history(self):
        with app.connection() as db:
            cid=crm.create(db,{'name':'Delete QA','tax_year':2025},'qa')['id']
            d=crm.detail(db,cid)
            other=crm.create(db,{'contact_id':d['contact_id'],'tax_year':2024},'qa')['id']
            preview=crm.deletion_preview(db,cid,'year')
            self.assertTrue(crm.soft_delete(db,{**preview,'confirmed_name':'Delete QA'},'qa'))
            self.assertEqual([r['id'] for r in crm.listing(db)],[other])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM clients').fetchone()[0],2)
            with self.assertRaises(ValueError):crm.detail(db,cid)
            batch=crm.trash(db)[0]['batch'];crm.restore(db,batch,'qa')
            self.assertEqual(len(crm.listing(db)),2)
            self.assertGreater(crm.detail(db,cid)['revision'],d['revision'])
            self.assertEqual(crm.trash(db),[])

    def test_contact_delete_and_restore_all_years(self):
        with app.connection() as db:
            cid=crm.create(db,{'name':'All Years QA','tax_year':2025},'qa')['id']
            d=crm.detail(db,cid)
            crm.create(db,{'contact_id':d['contact_id'],'tax_year':2024},'qa')
            preview=crm.deletion_preview(db,cid,'contact')
            self.assertEqual(len(preview['versions']),2)
            self.assertTrue(crm.soft_delete(db,{**preview,'confirmed_name':'All Years QA'},'qa'))
            self.assertEqual(crm.listing(db),[])
            with self.assertRaises(ValueError):crm.create(db,{'contact_id':d['contact_id'],'tax_year':2026},'qa')
            self.assertEqual(crm.restore(db,crm.trash(db)[0]['batch'],'qa')['restored'],2)

    def test_delete_confirmation_conflict_and_busy(self):
        with app.connection() as db:
            cid=crm.create(db,{'name':'Conflict QA','tax_year':2025},'qa')['id']
            preview=crm.deletion_preview(db,cid,'year')
            with self.assertRaises(ValueError):crm.soft_delete(db,{**preview,'confirmed_name':'Wrong'},'qa')
            d=crm.detail(db,cid);crm.save(db,cid,{**d,'notes':'concurrent edit'},'qa')
            self.assertFalse(crm.soft_delete(db,{**preview,'confirmed_name':'Conflict QA'},'qa'))
            db.execute("INSERT INTO documents(client_id,filename,status,page_count) VALUES(?,'busy.pdf','processing',1)",(cid,))
            preview=crm.deletion_preview(db,cid,'year')
            with self.assertRaises(ValueError):crm.soft_delete(db,{**preview,'confirmed_name':'Conflict QA'},'qa')

    def test_assignee_registry_case_insensitive_and_migration(self):
        with app.connection() as db:
            first=crm.add_assignee(db,{'name':'jacqueline'},'qa')
            again=crm.add_assignee(db,{'name':' Jacqueline '},'qa')
            self.assertEqual(first['id'],again['id'])
            self.assertEqual(len(crm.assignees(db)),1)
            with self.assertRaises(ValueError):crm.add_assignee(db,{'name':'  '},'qa')
            cid=crm.create(db,{'name':'Assignee QA','tax_year':2025},'qa')['id']
            d=crm.detail(db,cid)
            crm.save(db,cid,{**d,'assignee':'Existing Staff'},'qa')
        app.init_db()
        with app.connection() as db:
            self.assertEqual({r['name'] for r in crm.assignees(db)},{'jacqueline','Existing Staff'})

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=app.DATA
        app.DATA=Path(self.temp.name)/'data'
        app.init_db()

    def tearDown(self):
        app.DATA=self.old
        self.temp.cleanup()

    def test_legacy_migration_idempotent_no_name_merging(self):
        with app.connection() as db:
            for year in [2024,2025]:db.execute('INSERT INTO clients(alias,tax_year,created) VALUES(?,?,?)',('Same Name',year,'test'))
        app.init_db();app.init_db()
        with app.connection() as db:
            rows=crm.listing(db)
            self.assertEqual(len(rows),2)
            self.assertNotEqual(rows[0]['contact_id'],rows[1]['contact_id'])
            self.assertEqual({r['id'] for r in rows},{1,2})

    def test_years_contact_conflict_and_fee_roundtrip(self):
        with app.connection() as db:
            cid=crm.create(db,{'name':'QA Client','tax_year':2025},'editor')['id']
            first=crm.detail(db,cid)
            other=crm.create(db,{'contact_id':first['contact_id'],'tax_year':2026},'editor')['id']
            with self.assertRaises(ValueError):crm.create(db,{'contact_id':first['contact_id'],'tax_year':2026},'editor')
            payload={**first,'email':'qa@example.test','source_path':r'D:\QA\2025','fee':'500','paid':'100','due_date':'2026-04-15','stage':'待复核'}
            self.assertTrue(crm.save(db,cid,payload,'editor'))
            self.assertFalse(crm.save(db,cid,payload,'editor'))
            second=crm.detail(db,other)
            self.assertEqual(second['email'],'qa@example.test')
            self.assertEqual(second['fee'],'0.00')
            self.assertFalse(crm.save(db,other,{**second,'contact_revision':0},'editor'))
            self.assertEqual(crm.detail(db,cid)['fee'],'500.00')
            self.assertEqual(len(crm.detail(db,cid)['history']),2)

    def test_cross_workspace_links_and_page_validation(self):
        with app.connection() as db:
            a=crm.create(db,{'name':'A','tax_year':2025},'qa')['id']
            b=crm.create(db,{'name':'B','tax_year':2025},'qa')['id']
            did=db.execute("INSERT INTO documents(client_id,filename,role,status,page_count) VALUES(?,'qa.pdf','source','done',2)",(a,)).lastrowid
            iid=db.execute("INSERT INTO intake(client_id,label,owner,state,notes,reviewer,updated) VALUES(?,'W2','taxpayer','received','','qa','test')",(a,)).lastrowid
            data={'label':'W2 original','intake_id':iid,'document_id':did,'page_number':2}
            crm.link(db,a,data,'qa')
            with self.assertRaises(ValueError):crm.link(db,b,data,'qa')
            with self.assertRaises(ValueError):crm.link(db,a,{**data,'page_number':3},'qa')
            crm.link(db,a,{'label':'image','path':r'D:\QA\W2.png'},'qa')
            self.assertEqual(len(crm.detail(db,a)['links']),2)

    def test_backup_restore_preserves_crm(self):
        with app.connection() as db:
            cid=crm.create(db,{'name':'Backup QA','tax_year':2025},'qa')['id']
            d=crm.detail(db,cid)
            crm.save(db,cid,{**d,'proseries_path':r'D:\ProWin25\25Data\QA.25i'},'qa')
            crm.link(db,cid,{'label':'W2','path':r'D:\QA\W2.pdf'},'qa')
        backup=Path(self.temp.name)/'backup.zip';backup.write_bytes(app.build_backup())
        target=Path(self.temp.name)/'restored';restore_backup.restore(backup,target)
        with sqlite3.connect(target/'taxprep.sqlite3',factory=app.ClosingConnection) as db:
            self.assertEqual(db.execute('SELECT proseries_path FROM crm_years').fetchone()[0],r'D:\ProWin25\25Data\QA.25i')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM crm_links').fetchone()[0],1)


if __name__=='__main__':unittest.main()
