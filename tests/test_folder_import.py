import tempfile,unittest,sys
from pathlib import Path
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from taxtracker.runtime import app
from taxtracker.clients import crm
from taxtracker.clients import folder_import

class ImportTests(unittest.TestCase):
    def test_pdf_image_import_and_repeat_dedup(self):
        olddata,oldpool=app.DATA,app.POOL
        class Sync:
            def submit(self,fn,*args):fn(*args)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                root=Path(tmp);app.DATA=root/'data';app.init_db();app.POOL=Sync()
                with app.connection() as db:cid=crm.create(db,{'name':'Folder Import QA','tax_year':2025},'qa')['id']
                pdf=pymupdf.open();page=pdf.new_page();page.insert_text((50,50),'Form 1099-DIV\n1a Total Ordinary Dividends 10.00\n'+'Synthetic statement only. '*30)
                file=root/'source.pdf';pdf.save(file)
                image=root/'image.png';page.get_pixmap().save(image);pdf.close()
                files=[{'path':str(f),'name':f.name} for f in [file,image]]
                folder_import.enqueue(cid,files,'qa')
                with app.connection() as db:
                    d=crm.detail(db,cid);self.assertEqual(d['folder_job']['status'],'done');self.assertEqual(len(d['documents']),2);self.assertTrue(all(x['status']=='done' for x in d['documents']))
                with app.connection() as db:db.execute('DELETE FROM crm_folder_sources')
                folder_import.enqueue(cid,files,'qa')
                with app.connection() as db:self.assertEqual(len(crm.detail(db,cid)['documents']),2)
            finally:app.DATA,app.POOL=olddata,oldpool
