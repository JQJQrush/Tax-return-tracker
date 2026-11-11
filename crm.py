"""Persistent contacts and annual CRM metadata, retaining legacy workspace IDs."""
import datetime
import json
import sqlite3
import secrets
from core import money

STAGES = ['未开始','等待资料','处理中','待复核','待签字','待申报','已完成']
FILING = ['未提交','已提交','已接受','被退回','不适用']


def init(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS crm_years(client_id INTEGER PRIMARY KEY REFERENCES clients(id),contact_id INTEGER NOT NULL REFERENCES contacts(id),stage TEXT NOT NULL DEFAULT '未开始',assignee TEXT NOT NULL DEFAULT '',target_date TEXT NOT NULL DEFAULT '',due_date TEXT NOT NULL DEFAULT '',payment_due TEXT NOT NULL DEFAULT '',filing TEXT NOT NULL DEFAULT '未提交',fee TEXT NOT NULL DEFAULT '0.00',paid TEXT NOT NULL DEFAULT '0.00',source_path TEXT NOT NULL DEFAULT '',return_path TEXT NOT NULL DEFAULT '',proseries_path TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS crm_links(id INTEGER PRIMARY KEY,client_id INTEGER NOT NULL REFERENCES clients(id),intake_id INTEGER REFERENCES intake(id),document_id INTEGER REFERENCES documents(id),page_number INTEGER,label TEXT NOT NULL,path TEXT NOT NULL DEFAULT '',kind TEXT NOT NULL DEFAULT 'source');
    CREATE TABLE IF NOT EXISTS crm_history(id INTEGER PRIMARY KEY,client_id INTEGER NOT NULL REFERENCES clients(id),actor TEXT NOT NULL,event TEXT NOT NULL,before_json TEXT,after_json TEXT,created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS crm_assignees(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE COLLATE NOCASE,created_by TEXT NOT NULL,created TEXT NOT NULL);
    ''')
    db.execute('CREATE TABLE IF NOT EXISTS crm_trash(client_id INTEGER PRIMARY KEY REFERENCES clients(id),batch TEXT NOT NULL,scope TEXT NOT NULL,actor TEXT NOT NULL,deleted_at TEXT NOT NULL)')
    db.execute("CREATE TABLE IF NOT EXISTS crm_folder_jobs(client_id INTEGER PRIMARY KEY REFERENCES clients(id),status TEXT,total INTEGER,progress INTEGER,errors TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS crm_folder_sources(client_id INTEGER REFERENCES clients(id),path TEXT,hash TEXT,document_id INTEGER REFERENCES documents(id),PRIMARY KEY(client_id,path,hash))")
    db.execute("UPDATE crm_folder_jobs SET status='interrupted' WHERE status IN ('queued','running')")
    ensure(db)
    for row in db.execute("SELECT DISTINCT assignee FROM crm_years WHERE assignee<>''").fetchall():
        db.execute('INSERT OR IGNORE INTO crm_assignees(name,created_by,created) VALUES(?,?,?)',(row[0],'迁移',datetime.datetime.now(datetime.timezone.utc).isoformat()))


def assignees(db):
    return [dict(r) for r in db.execute('SELECT * FROM crm_assignees ORDER BY name COLLATE NOCASE')]


def add_assignee(db,data,actor):
    name=str(data.get('name','')).strip()
    if not name or len(name)>100 or any(ord(c)<32 for c in name):raise ValueError('请输入负责人姓名（最多100字）')
    db.execute('INSERT OR IGNORE INTO crm_assignees(name,created_by,created) VALUES(?,?,?)',(name,actor,datetime.datetime.now(datetime.timezone.utc).isoformat()))
    return dict(db.execute('SELECT * FROM crm_assignees WHERE name=? COLLATE NOCASE',(name,)).fetchone())


def ensure(db):
    for c in db.execute('SELECT * FROM clients WHERE id NOT IN (SELECT client_id FROM crm_years)').fetchall():
        person=db.execute('INSERT INTO contacts(name) VALUES(?)',(c['alias'],)).lastrowid
        db.execute('INSERT INTO crm_years(client_id,contact_id) VALUES(?,?)',(c['id'],person))


def history(db,cid,actor,event,before,after):
    db.execute('INSERT INTO crm_history(client_id,actor,event,before_json,after_json,created) VALUES(?,?,?,?,?,?)',
               (cid,actor,event,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),datetime.datetime.now(datetime.timezone.utc).isoformat()))


def listing(db):
    ensure(db)
    return [dict(r) for r in db.execute('SELECT c.id,c.tax_year,p.name alias,p.email,p.phone,y.* FROM clients c JOIN crm_years y ON y.client_id=c.id JOIN contacts p ON p.id=y.contact_id WHERE NOT EXISTS (SELECT 1 FROM crm_trash t WHERE t.client_id=c.id) ORDER BY p.name,c.tax_year DESC')]


def detail(db,cid):
    row=next((r for r in listing(db) if r['id']==cid),None)
    if row is None:raise ValueError('年度工作区不存在')
    row['contact_revision']=db.execute('SELECT revision FROM contacts WHERE id=?',(row['contact_id'],)).fetchone()[0]
    job=db.execute('SELECT * FROM crm_folder_jobs WHERE client_id=?',(cid,)).fetchone()
    row['folder_job']=dict(job) if job else None
    row['intake']=[dict(r) for r in db.execute('SELECT * FROM intake WHERE client_id=?',(cid,))]
    row['documents']=[dict(r) for r in db.execute('SELECT id,filename,role,status,page_count FROM documents WHERE client_id=?',(cid,))]
    forms={}
    for r in db.execute('SELECT p.document_id,r.payload FROM records r JOIN pages p ON p.id=r.page_id JOIN documents d ON d.id=p.document_id WHERE d.client_id=?',(cid,)):
        forms.setdefault(str(r['document_id']),set()).add(json.loads(r['payload'])['form_type'])
    row['document_forms']={k:sorted(v) for k,v in forms.items()}
    row['links']=[dict(r) for r in db.execute('SELECT * FROM crm_links WHERE client_id=?',(cid,))]
    row['history']=[dict(r) for r in db.execute('SELECT * FROM crm_history WHERE client_id=? ORDER BY id DESC LIMIT 100',(cid,))]
    return row


def create(db,data,actor):
    ensure(db)
    year=int(data.get('tax_year',2025))
    if not 2000<=year<=2100:raise ValueError('税年无效')
    pid=data.get('contact_id')
    if pid:
        person=db.execute('SELECT * FROM contacts WHERE id=?',(int(pid),)).fetchone()
        if not person:raise ValueError('客户不存在')
        if db.execute('SELECT 1 FROM crm_years y JOIN clients c ON c.id=y.client_id WHERE y.contact_id=? AND c.tax_year=?',(pid,year)).fetchone():raise ValueError('该客户已存在此年度')
        if not any(r['contact_id']==int(pid) for r in listing(db)):raise ValueError('客户已移入回收站，请先恢复')
        name=person['name']
    else:
        name=str(data.get('name','')).strip()
        if not name or len(name)>100:raise ValueError('请输入客户名称（最多100字）')
        pid=db.execute('INSERT INTO contacts(name) VALUES(?)',(name,)).lastrowid
    info=data.get('_folder_info')
    if info:
        matches=[r for r in listing(db) if r['tax_year']==year and r['source_path'].rstrip('\\/').casefold()==info['path'].rstrip('\\/').casefold()]
        if matches:
            if len(matches)==1 and matches[0]['alias'].casefold()==name.casefold():
                # Roll back the unused new contact created above when reusing a workspace.
                if not data.get('contact_id'):db.execute('DELETE FROM contacts WHERE id=?',(pid,))
                return {'id':matches[0]['id'],'existing':True,'name':matches[0]['alias']}
            raise ValueError('此文件夹已关联其他客户，请进入现有客户核对')
    cid=db.execute('INSERT INTO clients(alias,tax_year,created) VALUES(?,?,?)',(name,year,datetime.datetime.now(datetime.timezone.utc).isoformat())).lastrowid
    db.execute('INSERT INTO crm_years(client_id,contact_id) VALUES(?,?)',(cid,pid))
    history(db,cid,actor,'创建年度工作区',None,{'contact_id':pid,'tax_year':year})
    if info:
        db.execute('UPDATE crm_years SET source_path=? WHERE client_id=?',(info['path'],cid))
        for f in info['files']:
            link(db,cid,{'label':f['name'],'path':f['path'],'kind':'source'},actor)
        if info['evidence']:history(db,cid,actor,'从文件内容读取客户姓名',None,{'name':name,'evidence':info['evidence']})
    return {'id':cid,'name':name,'registered_files':len(info['files']) if info else 0}



def save(db,cid,data,actor):
    before=detail(db,cid)
    if data.get('revision')!=before['revision'] or data.get('contact_revision')!=before['contact_revision']:
        return False
    fields=['stage','assignee','target_date','due_date','payment_due','filing','fee','paid','source_path','return_path','proseries_path','notes']
    values={k:str(data.get(k,before[k])).strip() for k in fields}
    if values['stage'] not in STAGES or values['filing'] not in FILING:raise ValueError('状态无效')
    for key in ['target_date','due_date','payment_due']:
        if values[key]:datetime.date.fromisoformat(values[key])
    for key in ['fee','paid']:
        values[key]=money(values[key])
        if values[key] is None or values[key].startswith('-'):raise ValueError('服务费金额必须大于等于零')
    if any(len(v)>2000 for v in values.values()):raise ValueError('输入过长')
    name=str(data.get('alias',before['alias'])).strip()
    email=str(data.get('email',before['email'])).strip();phone=str(data.get('phone',before['phone'])).strip()
    if not name or len(name)>100 or len(email)>200 or len(phone)>100:raise ValueError('客户信息无效')
    db.execute('UPDATE contacts SET name=?,email=?,phone=?,revision=revision+1 WHERE id=?',(name,email,phone,before['contact_id']))
    db.execute('UPDATE clients SET alias=? WHERE id IN (SELECT client_id FROM crm_years WHERE contact_id=?)',(name,before['contact_id']))
    db.execute('UPDATE crm_years SET '+','.join(k+'=?' for k in fields)+',revision=revision+1 WHERE client_id=?',(*values.values(),cid))
    history(db,cid,actor,'修改客户/年度信息',{k:before[k] for k in fields+['alias','email','phone']},{**values,'alias':name,'email':email,'phone':phone})
    return True


def link(db,cid,data,actor):
    detail(db,cid)
    iid=int(data['intake_id']) if data.get('intake_id') else None
    did=int(data['document_id']) if data.get('document_id') else None
    page=int(data['page_number']) if data.get('page_number') else None
    if iid and not db.execute('SELECT 1 FROM intake WHERE id=? AND client_id=?',(iid,cid)).fetchone():raise ValueError('资料项目不属于此年度')
    if did:
        doc=db.execute('SELECT * FROM documents WHERE id=? AND client_id=?',(did,cid)).fetchone()
        if not doc:raise ValueError('文件不属于此年度')
        if iid and doc['role']!='source':raise ValueError('应交原始资料不能关联对照税表')
        if page and not 1<=page<=doc['page_count']:raise ValueError('页码超出范围')
    elif page:raise ValueError('页码需要关联已上传文件')
    label=str(data.get('label','')).strip();path=str(data.get('path','')).strip();kind=data.get('kind','source')
    if not label or len(label)>200 or len(path)>2000 or kind not in ['source','return','proseries']:raise ValueError('文件登记无效')
    if not did and not path:raise ValueError('请选择文件或填写路径')
    ident=db.execute('INSERT INTO crm_links(client_id,intake_id,document_id,page_number,label,path,kind) VALUES(?,?,?,?,?,?,?)',(cid,iid,did,page,label,path,kind)).lastrowid
    history(db,cid,actor,'关联资料文件',None,{'id':ident,'label':label,'path':path,'intake_id':iid,'document_id':did,'page_number':page,'kind':kind})
    return {'id':ident}


def deletion_preview(db,cid,scope):
    if scope not in ('year','contact'):raise ValueError('删除范围无效')
    current=detail(db,cid)
    rows=[r for r in listing(db) if r['id']==cid or (scope=='contact' and r['contact_id']==current['contact_id'])]
    ids=[r['id'] for r in rows]
    placeholders=','.join('?' for _ in ids)
    count=db.execute('SELECT COUNT(*) FROM documents WHERE client_id IN ('+placeholders+')',ids).fetchone()[0]
    busy=db.execute("SELECT 1 FROM documents WHERE client_id IN ("+placeholders+") AND status='processing'",ids).fetchone()
    return {'client_id':cid,'scope':scope,'alias':current['alias'],'contact_revision':current['contact_revision'],
            'versions':sorted([{'id':r['id'],'revision':r['revision']} for r in rows],key=lambda r:r['id']),
            'years':[r['tax_year'] for r in rows],'document_count':count,'busy':bool(busy)}


def soft_delete(db,data,actor):
    preview=deletion_preview(db,int(data['client_id']),data.get('scope'))
    if data.get('confirmed_name')!=preview['alias']:raise ValueError('请输入完整客户名称确认')
    if data.get('versions')!=preview['versions'] or data.get('contact_revision')!=preview['contact_revision'] or data.get('document_count')!=preview['document_count']:return False
    if db.execute("SELECT 1 FROM crm_folder_jobs WHERE client_id=? AND status IN ('queued','running')",(int(data['client_id']),)).fetchone():raise ValueError('文件夹正在导入，请完成后再删除')
    if preview['busy']:raise ValueError('该客户有正在识别的文件，请完成后再删除')
    batch=secrets.token_hex(16);now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    for row in preview['versions']:
        db.execute('INSERT INTO crm_trash(client_id,batch,scope,actor,deleted_at) VALUES(?,?,?,?,?)',(row['id'],batch,preview['scope'],actor,now))
        db.execute('UPDATE crm_years SET revision=revision+1 WHERE client_id=?',(row['id'],))
        history(db,row['id'],actor,'移入回收站',{'scope':preview['scope']},{'batch':batch})
    return True


def trash(db):
    result=[]
    for batch in db.execute('SELECT batch,scope,actor,deleted_at FROM crm_trash GROUP BY batch ORDER BY deleted_at DESC').fetchall():
        rows=[dict(r) for r in db.execute('SELECT c.id,c.tax_year,p.name FROM crm_trash t JOIN clients c ON c.id=t.client_id JOIN crm_years y ON y.client_id=c.id JOIN contacts p ON p.id=y.contact_id WHERE t.batch=?',(batch['batch'],))]
        result.append({**dict(batch),'name':rows[0]['name'],'years':[r['tax_year'] for r in rows]})
    return result


def restore(db,batch,actor):
    rows=db.execute('SELECT client_id FROM crm_trash WHERE batch=?',(batch,)).fetchall()
    if not rows:raise ValueError('回收站项目不存在或已恢复')
    for row in rows:
        history(db,row['client_id'],actor,'从回收站恢复',{'batch':batch},None)
        db.execute('UPDATE crm_years SET revision=revision+1 WHERE client_id=?',(row['client_id'],))
    db.execute('DELETE FROM crm_trash WHERE batch=?',(batch,))
    return {'restored':len(rows)}
