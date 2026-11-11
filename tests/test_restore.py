import hashlib,json,sqlite3,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import pymupdf as fitz
from taxtracker.operations.restore_backup import restore

class RestoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.old_data,self.old_pool=app.DATA,app.POOL
  app.DATA=self.root/'live';app.init_db()
  class Sync:
   def submit(self,fn,*args):fn(*args)
  app.POOL=Sync()
  with app.connection() as db:
   cid=db.execute('INSERT INTO clients(alias,tax_year,created) VALUES(?,?,?)',('Restoration test',2025,app.now())).lastrowid
   db.execute('INSERT INTO feedback(client_id,tester,area,severity,body,elapsed_seconds,created) VALUES(?,?,?,?,?,?,?)',(cid,'QA','review','suggestion','Keep this feedback',12,app.now()))
  doc=fitz.open();page=doc.new_page();page.insert_text((50,70),'Form 1099-DIV\n1a Total Ordinary Dividends 12.34\nSynthetic document for local testing only.');app.accept_document(cid,'synthetic.pdf','source',doc.tobytes());doc.close()
  self.live=app.DATA
 def tearDown(self):
  app.DATA,app.POOL=self.old_data,self.old_pool;self.tmp.cleanup()
 def archive(self,changes=None,remove=(),manifest=True):
  files={str(p.relative_to(self.live)).replace('\\','/'):p.read_bytes() for p in self.live.rglob('*') if p.is_file()}
  files.pop('app.lock',None)
  if manifest:files['backup-manifest.json']=json.dumps({'format':'taxprep-local-backup','format_version':1}).encode()
  for name in remove:files.pop(name,None)
  files.update(changes or {})
  path=self.root/'backup.zip'
  with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
   for name,data in files.items():z.writestr(name,data)
  return path
 def test_restore_and_check_only_preserve_records(self):
  archive=self.archive();summary=restore(archive,check_only=True)
  self.assertEqual(summary['records'],1);self.assertEqual(summary['feedback'],1)
  result=restore(archive,self.root/'restored');self.assertTrue(result['validated'])
  a=sqlite3.connect(self.live/'taxprep.sqlite3');b=sqlite3.connect(self.root/'restored'/'taxprep.sqlite3')
  try:self.assertEqual(a.execute('SELECT payload FROM records').fetchall(),b.execute('SELECT payload FROM records').fetchall())
  finally:a.close();b.close()
 def test_never_overwrite_existing_data(self):
  destination=self.root/'existing';destination.mkdir();(destination/'keep.txt').write_text('keep')
  with self.assertRaises(ValueError):restore(self.archive(),destination)
  self.assertEqual((destination/'keep.txt').read_text(),'keep')
 def test_tampered_pdf_rejected_atomically(self):
  with self.assertRaisesRegex(ValueError,'指纹'):restore(self.archive({'documents/1/original.pdf':b'%PDF tampered'}),self.root/'restored')
  self.assertFalse((self.root/'restored').exists());self.assertTrue((self.live/'taxprep.sqlite3').exists())
 def test_path_traversal_and_missing_preview_rejected(self):
  with self.assertRaises(ValueError):restore(self.archive({'../outside.txt':b'no'}),self.root/'restored')
  self.assertFalse((self.root/'outside.txt').exists())
  with self.assertRaisesRegex(ValueError,'预览'):restore(self.archive(remove=['documents/1/page-1.png']),self.root/'restored')
 def test_old_backup_can_upgrade_without_feedback_table(self):
  with app.connection() as db:db.execute('DROP TABLE feedback')
  restore(self.archive(manifest=False),self.root/'restored');app.DATA=self.root/'restored';app.init_db()
  with app.connection() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0],0)
 def test_future_format_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'格式版本'):restore(self.archive({'backup-manifest.json':b'{"format":"taxprep-local-backup","format_version":99}'}),self.root/'restored')

if __name__=='__main__':unittest.main()
