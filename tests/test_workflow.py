import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import io
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import pymupdf as fitz

class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();app.DATA=Path(cls.temp.name)
        app.init_db()
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
        cls.temp.cleanup()
    def call(self,path,data=None,token=True):
        headers={'X-Local-Token':app.TOKEN} if token else {}
        payload=None
        if data is not None:payload=json.dumps(data).encode();headers['Content-Type']='application/json'
        with urllib.request.urlopen(urllib.request.Request(self.url+path,data=payload,headers=headers)) as r:
            return json.load(r)
    def test_intake_roundtrip_conflicts_and_client_boundary(self):
        cid=self.call('/api/clients',{'alias':'intake-test','tax_year':2025})['id']
        data=dict(client_id=cid,label='W-2 TEST',owner='taxpayer',state='missing',notes='internal',reviewer='QA06')
        iid=self.call('/api/intake',data)['id']
        state=self.call('/api/workspace?client_id='+str(cid))
        self.assertEqual(state['intake'][0]['id'],iid)
        self.assertEqual(state['handoff']['task_counts']['missing_document'],1)
        data.update(id=iid,revision=0,state='not_applicable',notes='No employment')
        self.call('/api/intake',data)
        with self.assertRaises(urllib.error.HTTPError) as conflict:self.call('/api/intake',data)
        self.assertEqual(conflict.exception.code,409)
        other=self.call('/api/clients',{'alias':'other','tax_year':2025})['id']
        data.update(client_id=other,revision=1)
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/intake',data)
        data.update(client_id=cid,id=None,state='received',document_id=99999)
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/intake',data)
        with urllib.request.urlopen(urllib.request.Request(self.url+'/api/backup',headers={'X-Local-Token':app.TOKEN})) as r:raw=r.read()
        from taxtracker.operations import restore_backup
        import sqlite3
        with tempfile.TemporaryDirectory() as temp:
            backup=Path(temp)/'backup.zip';backup.write_bytes(raw);dest=Path(temp)/'restored'
            restore_backup.restore(backup,dest)
            with sqlite3.connect(dest/'taxprep.sqlite3', factory=app.ClosingConnection) as db:
                row=db.execute('SELECT state,revision FROM intake WHERE id=?',(iid,)).fetchone()
                self.assertEqual(row,('not_applicable',1))

    def test_api_requires_local_session(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:self.call('/api/clients',token=False)
        self.assertEqual(exc.exception.code,400)
    def test_demo_needs_no_ocr_and_keeps_source_separate(self):
        class SyncPool:
            def submit(self,fn,*args):fn(*args)
        old_pool,old_engine=app.POOL,app.tesseract_path
        app.POOL=SyncPool();app.tesseract_path=lambda:None
        try:
            cid=self.call('/api/demo',{})['id']
            workspace=self.call('/api/workspace?client_id='+str(cid))
            self.assertEqual(len(workspace['pages']),4)
            self.assertEqual(workspace['handoff']['page_total'],4)
            self.assertFalse(workspace['handoff']['filing_ready'])
            self.assertTrue(any(t['record_id'] for t in workspace['handoff']['tasks']))
            self.assertTrue(all(p['method']=='pdf_text' for p in workspace['pages']))
            w2=next(r for r in workspace['records'] if r['form_type']=='W-2')
            self.assertEqual(w2['values']['wages'],'1000.50')
            self.assertTrue(any(r['role']=='reference' and r['values'].get('wages')=='1001.00' for r in workspace['records']))
            self.assertTrue(all(r['status']=='pending' for r in workspace['records']))
            did=workspace['documents'][0]['id']
            with app.connection() as db:db.execute("UPDATE documents SET status='processing' WHERE id=?",(did,))
            try:
                with self.assertRaises(urllib.error.HTTPError) as busy:self.call('/api/backup')
                self.assertEqual(busy.exception.code,400)
            finally:
                with app.connection() as db:db.execute("UPDATE documents SET status='done' WHERE id=?",(did,))
            original=app.doc_dir(did)/'original.pdf';original_bytes=original.read_bytes()
            try:
                original.write_bytes(b'%PDF tampered')
                with self.assertRaises(urllib.error.HTTPError) as invalid:self.call('/api/backup')
                self.assertEqual(invalid.exception.code,400)
            finally:original.write_bytes(original_bytes)

        finally:app.POOL=old_pool;app.tesseract_path=old_engine

    def test_data_directory_process_lock(self):
        first=app.acquire_data_lock()
        try:
            with self.assertRaises(ValueError):app.acquire_data_lock()
        finally:first.close()
        with app.acquire_data_lock():pass

    def test_feedback_roundtrip(self):
        cid=self.call('/api/clients',{'alias':'Tester workspace','tax_year':2025})['id']
        result=self.call('/api/feedback',{'client_id':cid,'tester':'EMP02','area':'review','severity':'usability','body':'Synthetic feedback','elapsed_seconds':23})
        self.call('/api/feedback/'+str(result['id'])+'/state',{'state':'resolved'})
        rows=self.call('/api/feedback?client_id='+str(cid))['feedback']
        self.assertEqual(rows[0]['state'],'resolved');self.assertEqual(rows[0]['elapsed_seconds'],23)
        with self.assertRaises(urllib.error.HTTPError):
            self.call('/api/feedback',{'client_id':cid,'tester':'EMP02','area':'review','severity':'unknown','body':'Invalid'})

    def test_source_reference_and_audit(self):
        cid=self.call('/api/clients',{'alias':'Synthetic demo','tax_year':2025})['id']
        pdf=fitz.open();p=pdf.new_page();p.insert_text((60,60),'Form 1099-DIV\n1a Total Ordinary Dividends 100.25\n'+('Read this tax statement carefully. '*12));data=pdf.tobytes();pdf.close()
        # Synchronous pool makes all assertions deterministic.
        class SyncPool:
            def submit(self,fn,*args):fn(*args)
        old=app.POOL;app.POOL=SyncPool()
        try:
            first=app.accept_document(cid,'../../input.pdf','source',data)
            duplicate=app.accept_document(cid,'copy.pdf','source',data)
            self.assertTrue(duplicate['duplicate']);self.assertEqual(first['id'],duplicate['id'])
            with self.assertRaises(ValueError):app.accept_document(cid,'copy.pdf','reference',data)
            ws=self.call('/api/workspace?client_id='+str(cid));rec=ws['records'][0]
            self.assertEqual(rec['filename'],'input.pdf')
            self.assertEqual(rec['values']['ordinary_dividends'],'100.25')
            self.assertEqual(app.export_client(cid,True)['records'],[])
            proposal=self.call('/api/pages/'+str(rec['page_id'])+'/suggestions',{'form_type':'1099-DIV'})
            self.assertEqual(self.call('/api/workspace?client_id='+str(cid))['records'][0]['revision'],0)
            review={**rec,'proposal_token':proposal['token'],'owner':'taxpayer','reviewer':'EMP01','status':'reviewed','confirmed_blanks':True}
            self.call('/api/records/'+str(rec['id']),review)
            with self.assertRaises(urllib.error.HTTPError) as exc:self.call('/api/records/'+str(rec['id']),review)
            self.assertEqual(exc.exception.code,409)
            self.assertEqual(app.export_client(cid,True)['records'],[])
            self.call('/api/pages/'+str(rec['page_id'])+'/disposition',{'disposition':'included','reviewer':'EMP01'})
            report=app.export_client(cid,True);self.assertEqual(len(report['records']),1);self.assertFalse(report['filing_ready'])
            history=self.call('/api/records/'+str(rec['id'])+'/history')
            self.assertTrue(history['history'])
            with urllib.request.urlopen(urllib.request.Request(self.url+'/api/workpaper?client_id='+str(cid),headers={'X-Local-Token':app.TOKEN})) as response:
                self.assertIn('100.25',response.read().decode('utf-8'))
            self.call('/api/pages/'+str(rec['page_id'])+'/disposition',{'disposition':'excluded','reviewer':'EMP01'})
            self.assertEqual(app.export_client(cid,True)['records'],[])
            ref=fitz.open();p=ref.new_page();p.insert_text((60,60),'Form 1040 U.S. Individual Income Tax Return\n1a Wages 100.\n'+('Reference document only. '*15))
            refdata=ref.tobytes();ref.close()
            app.accept_document(cid,'return.pdf','reference',refdata)
            report=app.export_client(cid,True)
            self.assertTrue(report['reference_records'])
            self.assertEqual(report['records'],[])
            with app.connection() as db:self.assertGreaterEqual(db.execute('SELECT COUNT(*) FROM audit').fetchone()[0],2)
            with urllib.request.urlopen(urllib.request.Request(self.url+'/api/backup',headers={'X-Local-Token':app.TOKEN})) as response:
                archive=zipfile.ZipFile(io.BytesIO(response.read()))
                self.assertIn('taxprep.sqlite3',archive.namelist())
                with app.connection() as db: expected_documents=db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
                self.assertEqual(len([n for n in archive.namelist() if n.endswith('/original.pdf')]),expected_documents)
                self.assertIsNone(archive.testzip())
        finally:app.POOL=old

if __name__=='__main__':unittest.main()
