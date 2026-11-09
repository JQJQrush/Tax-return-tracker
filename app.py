"""Standalone localhost document-review application, Python 3.10+."""
import argparse
import concurrent.futures
import datetime
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import webbrowser
import zipfile

import fitz
from core import FIELDS, SCHEMA_VERSION, OCR_SEPARATOR, aligned_ocr_text, block_ocr_text, classify, export_rows, sha256, suggestions, validate_record
from extract import ocr_words,layout_candidates,combine_candidates
from intake import validate_item, reminder
from handoff import build_handoff
from review import checks
from workpaper import render_workpaper

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=1)
DATA = Path(os.environ.get('TAXPREP_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'TaxPrepLocal')))
MAX_UPLOAD = 50 * 1024 * 1024


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def acquire_data_lock():
    DATA.mkdir(parents=True,exist_ok=True)
    handle=(DATA/'app.lock').open('a+b')
    if handle.tell()==0:handle.write(b'0');handle.flush()
    handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ValueError('已有程序正在使用此数据目录，请先关闭旧版本或另一个窗口')
    return handle


def atomic_json(path,data):
    temporary=path.with_name('.'+path.name+'.'+secrets.token_hex(4)+'.tmp')
    try:
        temporary.write_text(json.dumps(data),encoding='utf-8')
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back on context exit, then release Windows file handles."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connection():
    conn = sqlite3.connect(DATA / 'taxprep.sqlite3', timeout=30, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'documents').mkdir(exist_ok=True)
    with connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, alias TEXT NOT NULL, tax_year INTEGER NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, client_id INTEGER REFERENCES clients(id), filename TEXT,
          hash TEXT, role TEXT, status TEXT, progress INTEGER DEFAULT 0, page_count INTEGER DEFAULT 0, error TEXT DEFAULT '', created TEXT,
          UNIQUE(client_id, hash));
        CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES documents(id), page_number INTEGER,
          text TEXT, method TEXT, rotation INTEGER, error TEXT DEFAULT '', disposition TEXT DEFAULT 'pending', reviewer TEXT DEFAULT '', UNIQUE(document_id,page_number));
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, page_id INTEGER REFERENCES pages(id), payload TEXT, evidence TEXT,
          revision INTEGER DEFAULT 0, updated TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, record_id INTEGER, event TEXT, before_json TEXT, after_json TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS intake(id INTEGER PRIMARY KEY,client_id INTEGER NOT NULL REFERENCES clients(id),
          label TEXT NOT NULL,owner TEXT NOT NULL,state TEXT NOT NULL,notes TEXT NOT NULL,reviewer TEXT NOT NULL,
          document_id INTEGER REFERENCES documents(id),revision INTEGER NOT NULL DEFAULT 0,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY,client_id INTEGER REFERENCES clients(id),tester TEXT,
          area TEXT,severity TEXT,body TEXT,elapsed_seconds INTEGER,state TEXT DEFAULT 'open',created TEXT);
        ''')
        if 'revision' not in {r[1] for r in db.execute('PRAGMA table_info(pages)')}:
            db.execute('ALTER TABLE pages ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')
        # Work interrupted by shutdown must never look complete.
        db.execute("UPDATE documents SET status='interrupted',error='上次处理被中断，可重新识别' WHERE status='processing'")


def tesseract_path():
    candidate = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
    if candidate and Path(candidate).is_file():
        return str(candidate)
    if os.name == 'nt':
        candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Tesseract-OCR' / 'tesseract.exe'
        if candidate.is_file():
            return str(candidate)
    return None


def doc_dir(doc_id):
    return DATA / 'documents' / str(int(doc_id))


def ocr_page(page, directory, number):
    native = page.get_text(sort=True).strip()
    useful = len(re.findall(r'[A-Za-z]{3,}', native))
    gibberish = sum(ord(c) < 32 and c not in '\n\r\t' or ord(c) > 126 for c in native)
    if (useful > 20 or (useful>=5 and not page.get_images())) and gibberish < max(10, len(native) * .03):
        words=[{'text':w[4],'box':[w[0]/page.rect.width,w[1]/page.rect.height,(w[2]-w[0])/page.rect.width,(w[3]-w[1])/page.rect.height],
                'confidence':None} for w in page.get_text('words')]
        atomic_json(directory/f'words-{number}.json',{'rotation':0,'words':words})
        return native, 'pdf_text', 0, ''
    engine = tesseract_path()
    if not engine:
        return native, 'manual', 0, '扫描件需要安装 Tesseract OCR；仍可查看原页并手工整理'
    image = directory / f'ocr-{number}.png'
    page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0)).save(image)
    rotation = 0
    try:
        osd = subprocess.run([engine, str(image), 'stdout', '--psm', '0'],
                             capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        match = re.search(r'Rotate:\s*(90|180|270)', osd.stdout)
        if match:
            # Tesseract reports clockwise rotation; fitz prerotate is clockwise.
            rotation = int(match.group(1))
        # Keep approximately 288 DPI for recognizing small brokerage amounts.
        pix=page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0).prerotate(rotation))
        pix.save(image)
        result = subprocess.run([engine, str(image), 'stdout', '-l', 'eng', '--psm', '3', 'tsv'],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
        if result.returncode:
            return native, 'manual', rotation, 'OCR 未成功，请手工核对此页或重新识别'
        text=aligned_ocr_text(result.stdout)+OCR_SEPARATOR+block_ocr_text(result.stdout)
        atomic_json(directory/f'words-{number}.json',{'rotation':rotation,'words':ocr_words(result.stdout,pix.width,pix.height)})
        return text, 'tesseract_dual_layout', rotation, ''
    finally:
        image.unlink(missing_ok=True)


def process_document(doc_id):
    directory = doc_dir(doc_id)
    try:
        with connection() as db:
            doc = db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
            db.execute("UPDATE documents SET status='processing',error='' WHERE id=?", (doc_id,))
        with fitz.open(directory / 'original.pdf') as pdf:
            for index, page in enumerate(pdf):
                with connection() as db:
                    exists = db.execute('SELECT id FROM pages WHERE document_id=? AND page_number=?', (doc_id, index+1)).fetchone()
                if exists:
                    continue  # Resume does not overwrite any reviewed work.
                try:
                    text, method, rotation, error = ocr_page(page, directory, index+1)
                except Exception:
                    text, method, rotation, error = '', 'manual', 0, '此页识别失败，请核对原页'
                page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5).prerotate(rotation)).save(directory / f'page-{index+1}.png')
                with connection() as db:
                    page_id = db.execute('INSERT INTO pages(document_id,page_number,text,method,rotation,error) VALUES(?,?,?,?,?,?)',
                                         (doc_id,index+1,text,method,rotation,error)).lastrowid
                    for form in classify(text, doc['role']):
                        evidence = suggestions(text, form)
                        word_file=directory/f'words-{index+1}.json'
                        if word_file.is_file():
                            stored=json.loads(word_file.read_text())
                            evidence=combine_candidates(evidence,layout_candidates(stored.get('words',[]) if isinstance(stored,dict) else stored,form))
                        payload = {'form_type': form, 'owner': 'return' if form=='1040-reference' else 'unknown',
                                   'values': {key: evidence.get(key, {}).get('value') for key,_ in FIELDS[form]},
                                   'status': 'pending', 'reviewer': '', 'confirmed_blanks': False,
                                   'payer': '', 'account_alias': '', 'category': 'unknown', 'entry_level':'unknown', 'notes': ''}
                        db.execute('INSERT INTO records(page_id,payload,evidence,updated) VALUES(?,?,?,?)',
                                   (page_id,json.dumps(payload),json.dumps(evidence),now()))
                    db.execute('UPDATE documents SET progress=? WHERE id=?', (index+1,doc_id))
            with connection() as db:
                db.execute("UPDATE documents SET status='done',progress=page_count WHERE id=?", (doc_id,))
    except Exception as exc:
        with connection() as db:
            db.execute("UPDATE documents SET status='error',error=? WHERE id=?", ('文件处理失败：'+type(exc).__name__,doc_id))


def accept_document(client_id, filename, role, content):
    if role not in ['source', 'reference']:
        raise ValueError('资料用途无效')
    if not content.startswith(b'%PDF'):
        raise ValueError('只接受 PDF 文件')
    with fitz.open(stream=content, filetype='pdf') as pdf:
        if pdf.needs_pass:
            raise ValueError('请先在本机另存为不带密码的 PDF')
        count = len(pdf)
        if not 1 <= count <= 200:
            raise ValueError('每份 PDF 需要 1–200 页，请将大文件拆分')
    digest = sha256(content)
    filename = filename.replace('\\', '/').split('/')[-1][:200] or 'document.pdf'
    with connection() as db:
        if not db.execute('SELECT 1 FROM clients WHERE id=?', (client_id,)).fetchone():
            raise ValueError('客户不存在')
        existing = db.execute('SELECT id,role FROM documents WHERE client_id=? AND hash=?', (client_id,digest)).fetchone()
        if existing:
            if existing['role'] != role:
                raise ValueError('相同文件已按另一用途上传；请使用原文件记录，不重复入账')
            return {'id':existing['id'], 'duplicate':True}
        doc_id = db.execute('INSERT INTO documents(client_id,filename,hash,role,status,page_count,created) VALUES(?,?,?,?,?,?,?)',
                            (client_id,filename,digest,role,'processing',count,now())).lastrowid
        directory = doc_dir(doc_id)
        directory.mkdir(parents=True)
        (directory / 'original.pdf').write_bytes(content)
    POOL.submit(process_document, doc_id)
    return {'id':doc_id, 'duplicate':False}


def list_records(db, client_id):
    rows = db.execute('''SELECT r.*,p.document_id,p.page_number,p.disposition,d.filename,d.role,c.tax_year,c.id client_id
                      FROM records r JOIN pages p ON p.id=r.page_id JOIN documents d ON d.id=p.document_id
                      JOIN clients c ON c.id=d.client_id WHERE c.id=? ORDER BY r.id''', (client_id,))
    result = []
    for row in rows:
        rec = dict(row)
        rec.update(json.loads(rec.pop('payload')))
        rec['evidence'] = json.loads(rec['evidence'])
        result.append(rec)
    return result


def export_client(client_id, reviewed_only=False):
    with connection() as db:
        client = db.execute('SELECT * FROM clients WHERE id=?', (client_id,)).fetchone()
        if not client:
            raise ValueError('客户不存在')
        records = list_records(db, client_id)
        docs = [dict(x) for x in db.execute('SELECT id,filename,hash,role,status,page_count,error FROM documents WHERE client_id=?',(client_id,))]
        unresolved_pages = db.execute('''SELECT COUNT(*) FROM pages p JOIN documents d ON d.id=p.document_id
                                         WHERE d.client_id=? AND d.role='source' AND p.disposition='pending' ''', (client_id,)).fetchone()[0]
        pages=[dict(p) for p in db.execute('SELECT p.*,d.role,d.filename FROM pages p JOIN documents d ON p.document_id=d.id WHERE d.client_id=?',(client_id,))]
    source = [r for r in records if r['role']=='source' and r['status']!='excluded' and r['disposition']!='excluded']
    included = [r for r in source if r['status']=='reviewed' and r.get('disposition')=='included'] if reviewed_only else source
    warnings = []
    if any(d['status']!='done' for d in docs):
        warnings.append('部分文件未识别完成')
    if any(r['status']!='reviewed' for r in source):
        warnings.append('仍有未审核收入记录')
    if unresolved_pages:
        warnings.append(f'{unresolved_pages} 个原始资料页面尚未确认用途')
    for doc in docs:
        if doc['role']=='source' and any(r['form_type']=='1099-B' and r['document_id']==doc['id'] for r in source):
            warnings.append('证券资料必须另外核对汇总与明细是否重复、交易分组及缺失成本；本版不自动判定可申报')
            break
    return {'schema_version':SCHEMA_VERSION,'export_kind':'reviewed_source_subset' if reviewed_only else 'draft_source_records',
            'generated_at':now(),'client':dict(client),'tax_software_import_supported':False,
            'filing_ready':False,'warnings':warnings,'documents':docs,'records':included,
            'reference_records':[r for r in records if r['role']=='reference'], 'review_checks':checks(records,pages,docs)}


def build_backup():
    # Snapshot the DB first; only copy immutable source/previews referenced by that snapshot.
    with tempfile.TemporaryDirectory() as temp:
        dbpath=Path(temp)/'taxprep.sqlite3'
        source=connection()
        try:
            with sqlite3.connect(dbpath, factory=ClosingConnection) as dest: source.backup(dest)
        finally: source.close()
        with sqlite3.connect(dbpath, factory=ClosingConnection) as snap:
            if snap.execute("SELECT 1 FROM documents WHERE status='processing'").fetchone():raise ValueError('请等当前文件识别完成后再备份')
            docs=list(snap.execute('SELECT id,hash FROM documents'))
            pages=list(snap.execute('SELECT document_id,page_number FROM pages'))
        from restore_backup import MAX_TOTAL,MAX_FILE
        selected=[dbpath]+[doc_dir(did)/'original.pdf' for did,_ in docs]+[doc_dir(did)/f'page-{number}.png' for did,number in pages]
        selected += [doc_dir(did)/f'words-{number}.json' for did,number in pages if (doc_dir(did)/f'words-{number}.json').is_file()]
        if any(not p.is_file() for p in selected):raise ValueError('原件或页面预览缺失，不能生成完整备份')
        sizes=[p.stat().st_size for p in selected]
        if len(selected)+1>20000 or sum(sizes)>MAX_TOTAL or any(size>MAX_FILE for size in sizes):raise ValueError('当前资料超过恢复支持的备份大小上限，请拆分资料目录后再备份')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.write(dbpath,'taxprep.sqlite3')
            archive.writestr('backup-manifest.json',json.dumps({'format':'taxprep-local-backup','format_version':1,'app_version':SCHEMA_VERSION,'created_at':now()}))
            for did,digest in docs:
                original=doc_dir(did)/'original.pdf'
                if not original.is_file():raise ValueError(f'文件 #{did} 原件缺失，不能生成完整备份')
                if sha256(original.read_bytes())!=digest:raise ValueError(f'文件 #{did} 原件指纹不一致，不能生成完整备份')
                archive.write(original,f'documents/{did}/original.pdf')
            for did,number in pages:
                image=doc_dir(did)/f'page-{number}.png'
                if not image.is_file():raise ValueError(f'文件 #{did} 第 {number} 页预览缺失，不能生成完整备份')
                archive.write(image,f'documents/{did}/page-{number}.png')
                word_file=doc_dir(did)/f'words-{number}.json'
                if word_file.is_file():archive.write(word_file,f'documents/{did}/words-{number}.json')
        return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Never put filenames, source text or identity data in HTTP logs.
        pass

    def send(self, value, status=200, content_type='application/json; charset=utf-8', extra=None):
        body = json.dumps(value,ensure_ascii=False).encode() if content_type.startswith('application/json') else value
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        for k,v in (extra or {}).items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(body)

    def guarded(self):
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        host = self.headers.get('Host','')
        if host not in allowed:
            raise ValueError('仅允许本机访问')
        if self.path.startswith('/api/') and not secrets.compare_digest(self.headers.get('X-Local-Token',''),TOKEN):
            raise ValueError('本机会话已失效，请刷新页面')

    def do_GET(self):
        try:
            self.guarded()
            parsed=urlparse(self.path); path=parsed.path; query=parse_qs(parsed.query)
            if path=='/':
                html=(ROOT/'index.html').read_text(encoding='utf-8').replace('__LOCAL_TOKEN__',TOKEN)
                return self.send(html.encode(),content_type='text/html; charset=utf-8')
            if path=='/api/config':
                return self.send({'fields':FIELDS,'ocr_available':bool(tesseract_path()),'version':SCHEMA_VERSION})
            if path=='/api/clients':
                with connection() as db:
                    rows=[dict(r) for r in db.execute('SELECT * FROM clients ORDER BY id DESC')]
                return self.send(rows)
            if path=='/api/workspace':
                cid=int(query['client_id'][0])
                with connection() as db:
                    docs=[dict(r) for r in db.execute('SELECT * FROM documents WHERE client_id=? ORDER BY id',(cid,))]
                    pages=[dict(r) for r in db.execute('''SELECT p.id,p.document_id,p.page_number,p.method,p.rotation,p.error,p.disposition,p.reviewer,p.revision,d.role,d.filename
                          FROM pages p JOIN documents d ON p.document_id=d.id WHERE d.client_id=? ORDER BY d.id,p.page_number''',(cid,))]
                    records=list_records(db,cid)
                    intake=[dict(r) for r in db.execute('SELECT * FROM intake WHERE client_id=? ORDER BY id',(cid,))]
                report=checks(records,pages,docs)
                return self.send({'documents':docs,'pages':pages,'records':records,'checks':report,
                                  'intake':intake,'handoff':build_handoff(records,pages,docs,report,intake)})
            if path=='/api/intake-reminder':
                cid=int(query['client_id'][0])
                with connection() as db:
                    client=db.execute('SELECT * FROM clients WHERE id=?',(cid,)).fetchone()
                    if not client:raise ValueError('客户不存在')
                    items=[dict(r) for r in db.execute('SELECT * FROM intake WHERE client_id=? ORDER BY id',(cid,))]
                return self.send(reminder(dict(client),items).encode('utf-8'),content_type='text/plain; charset=utf-8',extra={'Content-Disposition':'attachment; filename="missing-documents-draft.txt"'})
            if path=='/api/feedback':
                cid=int(query['client_id'][0])
                with connection() as db:
                    rows=[dict(r) for r in db.execute('SELECT * FROM feedback WHERE client_id=? ORDER BY id DESC',(cid,))]
                return self.send({'version':SCHEMA_VERSION,'feedback':rows},extra={'Content-Disposition':'attachment; filename="tester-feedback.json"'} if query.get('download') else None)
            match=re.fullmatch(r'/api/pages/(\d+)(/image)?',path)
            if match:
                with connection() as db:
                    p=db.execute('SELECT * FROM pages WHERE id=?',(int(match[1]),)).fetchone()
                if not p:
                    return self.send({'error':'页面不存在'},404)
                if match[2]:
                    return self.send((doc_dir(p['document_id'])/f"page-{p['page_number']}.png").read_bytes(),content_type='image/png')
                return self.send(dict(p))
            if path=='/api/export':
                cid=int(query['client_id'][0]); kind=query.get('kind',['draft'])[0]
                data=export_client(cid,reviewed_only=kind=='csv')
                if kind=='csv':
                    if any(i['severity']=='error' for i in data['review_checks']['issues']):
                        raise ValueError('存在金额算式冲突或证券重复层级，请处理后再导出已核对 CSV；仍可导出 JSON 草稿')
                    return self.send(('\ufeff'+export_rows(data['records'])).encode(),content_type='text/csv; charset=utf-8',
                                     extra={'Content-Disposition':'attachment; filename="reviewed-source-subset.csv"'})
                return self.send(data,extra={'Content-Disposition':'attachment; filename="tax-review-draft.json"'})
            if path=='/api/workpaper':
                data=export_client(int(query['client_id'][0]))
                scope=query.get('scope',['reviewed'])[0]
                html=render_workpaper(data,scope)
                return self.send(html.encode('utf-8'),content_type='text/html; charset=utf-8',extra={'Content-Disposition':'attachment; filename="tax-input-workpaper.html"'})
            match=re.fullmatch(r'/api/records/(\d+)/history',path)
            if match:
                with connection() as db:
                    exists=db.execute('SELECT id FROM records WHERE id=?',(int(match[1]),)).fetchone()
                    if not exists:raise ValueError('记录不存在')
                    history=[dict(r) for r in db.execute('SELECT id,event,before_json,after_json,created FROM audit WHERE record_id=? ORDER BY id DESC',(int(match[1]),))]
                return self.send({'history':history,'notice':'仅显示此记录已保存的修改；页面用途变更请另核对当前页面状态。'})
            if path=='/api/backup':
                return self.send(build_backup(),content_type='application/zip',
                                 extra={'Content-Disposition':'attachment; filename="taxprep-local-backup.zip"'})
            return self.send({'error':'页面不存在'},404)
        except (ValueError, KeyError) as exc:
            self.send({'error':str(exc)},400)
        except Exception:
            self.send({'error':'读取失败，请检查文件或重启本机程序'},500)

    def do_POST(self):
        try:
            self.guarded()
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=MAX_UPLOAD:
                raise ValueError('文件或请求为空，或超过 50MB')
            parsed=urlparse(self.path); path=parsed.path; query=parse_qs(parsed.query)
            raw=self.rfile.read(length)
            if path=='/api/upload':
                result=accept_document(int(query['client_id'][0]),query.get('filename',['document.pdf'])[0],
                                       query.get('role',['source'])[0],raw)
                return self.send(result)
            data=json.loads(raw)
            if getattr(self, 'user', None):
                data['reviewer'] = self.user['username']
                data['tester'] = self.user['username']
            if path=='/api/demo':
                from demo import demo_documents
                with connection() as db:
                    cid=db.execute('INSERT INTO clients(alias,tax_year,created) VALUES(?,?,?)',('演示客户（合成资料）',2025,now())).lastrowid
                source,reference=demo_documents()
                accept_document(cid,'synthetic-income-samples.pdf','source',source)
                accept_document(cid,'synthetic-reference.pdf','reference',reference)
                return self.send({'id':cid,'notice':'全部为合成测试数据，无真实身份信息'})
            if path=='/api/intake':
                cid=int(data['client_id']);item=validate_item(data);iid=data.get('id')
                with connection() as db:
                    if not db.execute('SELECT 1 FROM clients WHERE id=?',(cid,)).fetchone():raise ValueError('客户不存在')
                    if item['document_id'] is not None and not db.execute('SELECT 1 FROM documents WHERE id=? AND client_id=? AND role=?',(item['document_id'],cid,'source')).fetchone():raise ValueError('只能关联此客户的原始资料文件')
                    before=None
                    if iid is not None:
                        row=db.execute('SELECT * FROM intake WHERE id=? AND client_id=?',(int(iid),cid)).fetchone()
                        if not row:raise ValueError('资料项目不存在')
                        before=dict(row)
                        if data.get('revision')!=row['revision']:return self.send({'error':'项目已被修改，请刷新后重试'},409)
                        db.execute('UPDATE intake SET label=?,owner=?,state=?,notes=?,reviewer=?,document_id=?,revision=revision+1,updated=? WHERE id=?',(*[item[k] for k in ('label','owner','state','notes','reviewer','document_id')],now(),int(iid)))
                    else:
                        iid=db.execute('INSERT INTO intake(client_id,label,owner,state,notes,reviewer,document_id,updated) VALUES(?,?,?,?,?,?,?,?)',(cid,*[item[k] for k in ('label','owner','state','notes','reviewer','document_id')],now())).lastrowid
                    db.execute('INSERT INTO audit(event,before_json,after_json,created) VALUES(?,?,?,?)',('intake_update',json.dumps(before),json.dumps(dict(id=iid,client_id=cid,**item)),now()))
                return self.send({'id':iid,'saved':True})
            if path=='/api/feedback':
                cid=int(data['client_id']);tester=str(data.get('tester','')).strip()[:100];body=str(data.get('body','')).strip()[:4000]
                area=data.get('area');severity=data.get('severity');elapsed=int(data.get('elapsed_seconds') or 0)
                if not tester or not body or area not in ['install','extraction','review','export','other'] or severity not in ['blocking','wrong_value','usability','suggestion'] or not 0<=elapsed<=86400:
                    raise ValueError('请填写测试人、问题内容和有效测试类型/用时')
                with connection() as db:
                    if not db.execute('SELECT 1 FROM clients WHERE id=?',(cid,)).fetchone():raise ValueError('客户不存在')
                    fid=db.execute('INSERT INTO feedback(client_id,tester,area,severity,body,elapsed_seconds,created) VALUES(?,?,?,?,?,?,?)',
                                   (cid,tester,area,severity,body,elapsed,now())).lastrowid
                return self.send({'id':fid})
            match=re.fullmatch(r'/api/feedback/(\d+)/state',path)
            if match:
                if data.get('state') not in ['open','resolved']:raise ValueError('反馈状态无效')
                with connection() as db:
                    row=db.execute('SELECT * FROM feedback WHERE id=?',(int(match[1]),)).fetchone()
                    if not row:raise ValueError('反馈不存在')
                    db.execute('UPDATE feedback SET state=? WHERE id=?',(data['state'],row['id']))
                    db.execute('INSERT INTO audit(event,before_json,after_json,created) VALUES(?,?,?,?)',('feedback_state',json.dumps(dict(row)),json.dumps(data),now()))
                return self.send({'saved':True})
            if path=='/api/clients':
                alias=str(data.get('alias','')).strip()[:100]; year=int(data.get('tax_year',2025))
                if not alias or not 2000<=year<=2100:
                    raise ValueError('请填写客户代号和有效税务年度')
                with connection() as db:
                    cid=db.execute('INSERT INTO clients(alias,tax_year,created) VALUES(?,?,?)',(alias,year,now())).lastrowid
                return self.send({'id':cid})
            match=re.fullmatch(r'/api/records/(\d+)',path)
            if match:
                with connection() as db:
                    row=db.execute('SELECT r.*,d.role FROM records r JOIN pages p ON r.page_id=p.id JOIN documents d ON p.document_id=d.id WHERE r.id=?',(int(match[1]),)).fetchone()
                    if not row:
                        raise ValueError('记录不存在')
                    if int(data.get('revision',-1))!=row['revision']:
                        return self.send({'error':'记录已被其他窗口修改，请刷新后再核对'},409)
                    payload=validate_record(data)
                    if (row['role']=='reference')!=(payload['form_type']=='1040-reference'):
                        raise ValueError('对照税表不能作为原始收入录入')
                    encoded=json.dumps(payload)
                    prior=json.loads(row['evidence']) if json.loads(row['payload'])['form_type']==payload['form_type'] else {}
                    evidence={k:v for k,v in prior.items() if payload['values'].get(k)==v.get('value')}
                    if data.get('proposal_token'):
                        proposal_file=doc_dir(db.execute('SELECT document_id FROM pages WHERE id=?',(row['page_id'],)).fetchone()['document_id'])/f"proposal-{row['page_id']}-{payload['form_type']}.json"
                        if not proposal_file.is_file():raise ValueError('提取建议已失效，请重新获取')
                        staged=json.loads(proposal_file.read_text())
                        if not secrets.compare_digest(str(data['proposal_token']),staged['token']):raise ValueError('提取建议已更新，请重新获取')
                        evidence.update({k:v for k,v in staged['suggestions'].items() if payload['values'].get(k)==v.get('value')})
                    db.execute('UPDATE records SET payload=?,evidence=?,revision=revision+1,updated=? WHERE id=?',(encoded,json.dumps(evidence),now(),row['id']))
                    db.execute('INSERT INTO audit(record_id,event,before_json,after_json,created) VALUES(?,?,?,?,?)',(row['id'],'update',row['payload'],encoded,now()))
                return self.send({'saved':True})
            match=re.fullmatch(r'/api/pages/(\d+)/records',path)
            if match:
                form=data.get('form_type')
                with connection() as db:
                    row=db.execute('SELECT p.id,d.role FROM pages p JOIN documents d ON p.document_id=d.id WHERE p.id=?',(int(match[1]),)).fetchone()
                    if not row or form not in FIELDS:
                        raise ValueError('表格或页面无效')
                    if (row['role']=='reference')!=(form=='1040-reference'):
                        raise ValueError('原资料与完成税表必须分开')
                    payload={'form_type':form,'owner':'return' if form=='1040-reference' else 'unknown','values':{},'status':'pending'}
                    rid=db.execute('INSERT INTO records(page_id,payload,evidence,updated) VALUES(?,?,?,?)',(row['id'],json.dumps(payload),'{}',now())).lastrowid
                    db.execute('INSERT INTO audit(record_id,event,after_json,created) VALUES(?,?,?,?)',(rid,'create',json.dumps(payload),now()))
                return self.send({'id':rid})
            match=re.fullmatch(r'/api/pages/(\d+)/suggestions',path)
            if match:
                form=data.get('form_type')
                if form not in FIELDS:raise ValueError('表格类型无效')
                with connection() as db:
                    p=db.execute('SELECT * FROM pages WHERE id=?',(int(match[1]),)).fetchone()
                    if not p:raise ValueError('页面不存在')
                    role=db.execute('SELECT role FROM documents WHERE id=?',(p['document_id'],)).fetchone()['role']
                if (role=='reference')!=(form=='1040-reference'):raise ValueError('资料用途与表格不一致')
                directory=doc_dir(p['document_id']);word_file=directory/f"words-{p['page_number']}.json"
                text=p['text'];same_rotation=True
                if not word_file.is_file():
                    with fitz.open(directory/'original.pdf') as pdf:
                        text,method,rotation,error=ocr_page(pdf[p['page_number']-1],directory,p['page_number'])
                        if error:raise ValueError(error)
                        same_rotation=rotation==p['rotation']
                stored=json.loads(word_file.read_text()) if word_file.is_file() else []
                words=stored.get('words',[]) if isinstance(stored,dict) else stored
                if isinstance(stored,dict):same_rotation=stored.get('rotation')==p['rotation']
                proposal=combine_candidates(suggestions(text,form),layout_candidates(words,form))
                if not same_rotation:
                    for item in proposal.values():item.pop('box',None)
                token=secrets.token_urlsafe(24)
                atomic_json(directory/f"proposal-{p['id']}-{form}.json",{'token':token,'suggestions':proposal})
                return self.send({'suggestions':proposal,'token':token,'notice':'仅提供候选，未改动任何已保存字段或审核状态'})
            match=re.fullmatch(r'/api/pages/(\d+)/disposition',path)
            if match:
                disposition=data.get('disposition'); reviewer=str(data.get('reviewer','')).strip()[:100]
                if disposition not in ['pending','included','excluded'] or (disposition!='pending' and not reviewer):
                    raise ValueError('请填写页面用途和审核人')
                with connection() as db:
                    row=db.execute('SELECT * FROM pages WHERE id=?',(int(match[1]),)).fetchone()
                    if not row: raise ValueError('页面不存在')
                    if getattr(self, 'user', None) and data.get('revision') != row['revision']:
                        return self.send({'error':'页面已被其他员工修改，请刷新后重试'},409)
                    db.execute('UPDATE pages SET disposition=?,reviewer=?,revision=revision+1 WHERE id=?',(disposition,reviewer,row['id']))
                    db.execute('INSERT INTO audit(event,before_json,after_json,created) VALUES(?,?,?,?)',
                               ('page_disposition',json.dumps(dict(row)),json.dumps({'page_id':row['id'],**data}),now()))
                return self.send({'saved':True})
            match=re.fullmatch(r'/api/documents/(\d+)/resume',path)
            if match:
                with connection() as db:
                    row=db.execute('SELECT * FROM documents WHERE id=?',(int(match[1]),)).fetchone()
                    if not row or row['status']=='processing': raise ValueError('文件不存在或正在处理')
                    # Retain pages with records or manually confirmed dispositions.
                    db.execute("DELETE FROM pages WHERE document_id=? AND method='manual' AND disposition='pending' AND NOT EXISTS(SELECT 1 FROM records WHERE records.page_id=pages.id)",(row['id'],))
                    db.execute("UPDATE documents SET status='processing' WHERE id=?",(row['id'],))
                POOL.submit(process_document,row['id'])
                return self.send({'queued':True})
            return self.send({'error':'操作不存在'},404)
        except (ValueError,KeyError,TypeError,fitz.FileDataError) as exc:
            self.send({'error':str(exc)},400)
        except Exception:
            self.send({'error':'保存失败，请检查数据并重试'},500)


def main():
    global DATA
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if args.data_dir: DATA=args.data_dir.resolve()
    try:data_lock=acquire_data_lock()
    except ValueError as exc:raise SystemExit(str(exc))
    try:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError:
        data_lock.close()
        raise SystemExit('端口已占用，请关闭已运行的窗口或用 --port 8766 启动')
    try:init_db()
    except Exception:
        server.server_close();data_lock.close();raise
    url=f'http://127.0.0.1:{args.port}'
    print('TaxPrep Local 0.4 — 本机资料核对工作台')
    print('打开：'+url)
    print('只在本机运行。关闭前请等文件识别完成；Ctrl+C 停止。')
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        POOL.shutdown(wait=True)
        data_lock.close()


if __name__=='__main__': main()
