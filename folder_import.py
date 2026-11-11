"""Background ingestion of user-selected folders into the existing OCR queue."""
import hashlib,json
from pathlib import Path
import pymupdf
import app,crm
from core import classify


def run(cid,files,actor):
    errors=[];completed=0
    with app.connection() as db:db.execute("UPDATE crm_folder_jobs SET status='running' WHERE client_id=?",(cid,))
    try:
        for info in files:
            path=Path(info['path'])
            try:
                if path.stat().st_size>app.MAX_UPLOAD:raise ValueError('文件超过50MB')
                raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
                with app.connection() as db:
                    crm.detail(db,cid)
                    known=db.execute('SELECT document_id FROM crm_folder_sources WHERE client_id=? AND path=? AND hash=?',(cid,str(path),digest)).fetchone()
                if known:
                    completed+=1;continue
                if path.suffix.lower()=='.pdf':content=raw
                else:
                    with pymupdf.open(path) as image:content=image.convert_to_pdf()
                with pymupdf.open(stream=content,filetype='pdf') as pdf:
                    role='reference' if any(classify(pdf[i].get_text(),'reference') for i in range(min(2,len(pdf)))) else 'source'
                # Reuse a pre-existing managed PDF with identical bytes.
                reused=None
                if path.suffix.lower()!='.pdf':
                    with app.connection() as db:
                        linked=db.execute('SELECT DISTINCT document_id FROM crm_links WHERE client_id=? AND path=? AND document_id IS NOT NULL',(cid,str(path))).fetchall()
                    original=pymupdf.Pixmap(path)
                    for candidate in linked:
                        try:
                            with pymupdf.open(app.doc_dir(candidate[0])/'original.pdf') as stored:
                                for xref,*_ in stored.get_page_images(0):
                                    pixels=pymupdf.Pixmap(stored,xref)
                                    if pixels.width==original.width and pixels.height==original.height and pixels.digest==original.digest:reused=candidate[0];break
                            if reused:break
                        except (OSError,RuntimeError):continue
                result={'id':reused,'duplicate':True} if reused else app.accept_document(cid,path.name if path.suffix.lower()=='.pdf' else path.stem+' [image].pdf',role,content)
                did=result['id']
                with app.connection() as db:
                    db.execute('INSERT OR REPLACE INTO crm_folder_sources(client_id,path,hash,document_id) VALUES(?,?,?,?)',(cid,str(path),digest,did))
                    link=db.execute('SELECT id FROM crm_links WHERE client_id=? AND path=? AND document_id IS NULL',(cid,str(path))).fetchone()
                    if link:db.execute('UPDATE crm_links SET document_id=?,kind=? WHERE id=?',(did,'return' if role=='reference' else 'source',link['id']))
                    elif not db.execute('SELECT 1 FROM crm_links WHERE client_id=? AND path=? AND document_id=?',(cid,str(path),did)).fetchone():crm.link(db,cid,{'label':path.name,'document_id':did,'path':str(path),'kind':'return' if role=='reference' else 'source'},actor)
                    crm.history(db,cid,actor,'从文件夹导入资料',None,{'file':path.name,'document_id':did,'role':role})
                completed+=1
            except Exception as exc:errors.append({'file':path.name,'error':str(exc)[:300]})
            with app.connection() as db:db.execute('UPDATE crm_folder_jobs SET progress=?,errors=? WHERE client_id=?',(completed,json.dumps(errors,ensure_ascii=False),cid))
    finally:
        with app.connection() as db:db.execute('UPDATE crm_folder_jobs SET status=?,progress=?,errors=? WHERE client_id=?',('partial' if errors else 'done',completed,json.dumps(errors,ensure_ascii=False),cid))


def enqueue(cid,files,actor):
    with app.connection() as db:
        crm.detail(db,cid)
        existing=db.execute('SELECT status FROM crm_folder_jobs WHERE client_id=?',(cid,)).fetchone()
        if existing and existing['status'] in ('queued','running'):return
        db.execute("INSERT OR REPLACE INTO crm_folder_jobs(client_id,status,total,progress,errors) VALUES(?,'queued',?,0,'[]')",(cid,len(files)))
    app.POOL.submit(run,cid,files,actor)
