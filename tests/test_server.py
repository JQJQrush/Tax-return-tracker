import concurrent.futures
import http.cookiejar
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taxtracker.operations import accounts
import app
import server
from taxtracker.operations.restore_backup import restore

PASSWORD = 'Synthetic-test-password-2026'


class Browser:
    def __init__(self, url):
        self.url = url
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ''

    def request(self, path, data=None, headers=None, raw=None):
        request_headers = {'X-Local-Token': self.csrf}
        body = raw
        if data is not None:
            body = json.dumps(data).encode()
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        request = urllib.request.Request(self.url + path, data=body, headers=request_headers)
        try:
            response = self.opener.open(request, timeout=20)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read()
            value = json.loads(body) if response.headers.get_content_type() == 'application/json' else body
            return response.status, value, response.headers

    def login(self, username, password=PASSWORD):
        status, _, headers = self.request('/api/login', {'username': username, 'password': password})
        if status == 200:
            status, html, _ = self.request('/')
            self.csrf = re.search(rb"const token='([^']+)'", html).group(1).decode()
        return status, headers


class ServerTests(unittest.TestCase):
    def test_create_from_folder_only_and_reuse_workspace(self):
        admin=self.browser('admin');reader=self.browser('reader')
        with tempfile.TemporaryDirectory() as folder:
            import pymupdf
            doc=pymupdf.open();page=doc.new_page()
            page.insert_text((50,50),"Taxpayer's name                 Social security number\nFOLDER QA PERSON                 000-00-0000")
            doc.save(Path(folder)/'taxpayer.pdf');doc.close()
            self.assertEqual(reader.request('/api/crm/preview-folder',{'source_path':folder})[0],403)
            status,preview,_=admin.request('/api/crm/preview-folder',{'source_path':folder})
            self.assertEqual(status,200);self.assertEqual(preview['files'][0]['name'],'taxpayer.pdf')
            payload={'name':'','source_path':folder,'tax_year':2025}
            self.assertEqual(reader.request('/api/crm/create',payload)[0],403)
            status,created,_=admin.request('/api/crm/create',payload)
            self.assertEqual(status,200);self.assertEqual(created['name'],'FOLDER QA PERSON')
            cid=created['id']
            detail=admin.request('/api/crm?id='+str(cid))[1]
            self.assertEqual(detail['source_path'],folder);self.assertEqual(len(detail['links']),1)
            self.assertEqual(detail['alias'],'FOLDER QA PERSON')
            with app.connection() as db:before=db.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
            status,again,_=admin.request('/api/crm/create',payload)
            self.assertEqual(status,200);self.assertEqual(again['id'],cid);self.assertTrue(again['existing'])
            with app.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM contacts').fetchone()[0],before)
            self.assertEqual(admin.request('/api/crm/create',{'name':'','source_path':'','tax_year':2025})[0],400)

    def test_customer_trash_permissions_and_old_workspace_access(self):
        admin=self.browser('admin');editor=self.browser('alice');reader=self.browser('reader')
        status,result,_=admin.request('/api/crm/create',{'name':'HTTP Trash QA','tax_year':2025})
        self.assertEqual(status,200);cid=result['id']
        status,preview,_=admin.request('/api/crm/delete-preview?id='+str(cid)+'&scope=year')
        self.assertEqual(status,200)
        payload={**preview,'confirmed_name':'HTTP Trash QA'}
        for user in [reader,editor]:
            self.assertEqual(user.request('/api/crm/delete',payload)[0],403)
            self.assertEqual(user.request('/api/crm/trash')[0],403)
        self.assertEqual(admin.request('/api/crm/delete',payload)[0],200)
        self.assertEqual(admin.request('/api/workspace?client_id='+str(cid))[0],409)
        self.assertNotIn(cid,[r['id'] for r in admin.request('/api/clients')[1]])
        trash=admin.request('/api/crm/trash')[1]
        batch=next(t['batch'] for t in trash if t['name']=='HTTP Trash QA')
        self.assertEqual(editor.request('/api/crm/restore',{'batch':batch})[0],403)
        self.assertEqual(admin.request('/api/crm/restore',{'batch':batch})[0],200)
        self.assertEqual(admin.request('/api/workspace?client_id='+str(cid))[0],200)

    def test_crm_permissions_conflicts_and_workspace_entry(self):
        editor=Browser(self.url);self.assertEqual(editor.login('alice')[0],200)
        status,created,_=editor.request('/api/crm/create',{'name':'CRM API QA','tax_year':2025})
        self.assertEqual(status,200)
        cid=created['id']
        status,detail,_=editor.request('/api/crm?id='+str(cid));self.assertEqual(status,200)
        payload={**detail,'client_id':cid,'stage':'待复核','fee':'250','paid':'50'}
        self.assertEqual(editor.request('/api/crm/save',payload)[0],200)
        self.assertEqual(editor.request('/api/crm/save',payload)[0],409)
        self.assertEqual(editor.request('/api/crm/link',{'client_id':cid,'label':'ProSeries','kind':'proseries','path':r'D:\QA\client.25i'})[0],200)
        reader=Browser(self.url);self.assertEqual(reader.login('reader')[0],200)
        self.assertEqual(editor.request('/api/crm/assignees',{'name':'jacqueline'})[0],200)
        self.assertEqual(reader.request('/api/crm/assignees')[0],200)
        self.assertEqual(reader.request('/api/crm/assignees',{'name':'blocked'})[0],403)
        self.assertEqual(reader.request('/api/crm')[0],200)
        for route in ['create','save','link']:
            self.assertEqual(reader.request('/api/crm/'+route,payload)[0],403)
        status,html,_=editor.request('/workspace?client_id='+str(cid))
        self.assertEqual(status,200);self.assertIn('返回客户总表'.encode(),html)
        status,html,_=editor.request('/')
        self.assertEqual(status,200);self.assertIn('客户总表'.encode(),html)

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.old_data, cls.old_pool = app.DATA, app.POOL
        app.DATA = Path(cls.temp.name)/'live'
        app.init_db()
        with app.connection() as db:
            accounts.init(db)
            for name, role in [('admin','admin'),('alice','editor'),('bob','editor'),('reader','viewer')]:
                accounts.save_user(db, name, role, PASSWORD)
        class Sync:
            def submit(self, fn, *args):
                fn(*args)
        app.POOL = Sync()
        cls.http = server.OfficeServer(('127.0.0.1',0), server.Handler)
        cls.url = 'http://127.0.0.1:' + str(cls.http.server_port)
        server.configure(cls.http, [cls.url.removeprefix('http://')], False)
        cls.thread = threading.Thread(target=cls.http.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        app.DATA, app.POOL = cls.old_data, cls.old_pool
        cls.temp.cleanup()

    def browser(self, name):
        browser = Browser(self.url)
        self.assertEqual(browser.login(name)[0], 200)
        return browser

    def demo(self, browser):
        status, result, _ = browser.request('/api/demo', {})
        self.assertEqual(status, 200)
        status, workspace, _ = browser.request('/api/workspace?client_id='+str(result['id']))
        self.assertEqual(status, 200)
        return result['id'], workspace

    def test_unauthenticated_all_data_and_legacy_token_denied(self):
        browser = Browser(self.url)
        for path in ['/api/clients','/api/config','/api/pages/1/image','/api/backup','/api/users',
                     '/api/workspace?client_id=1','/api/export?client_id=1','/api/server-events']:
            self.assertEqual(browser.request(path, headers={'X-Local-Token':app.TOKEN})[0], 401, path)
        self.assertEqual(browser.request('/api/clients', {'alias':'blocked','tax_year':2025})[0],401)
        status, html, headers = browser.request('/')
        self.assertEqual(status, 200)  # redirect lands on the login form
        self.assertIn(b'current-password', html)
        self.assertNotIn(app.TOKEN.encode(), html)
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_cookie_and_csrf_origin_host_guards(self):
        browser = self.browser('alice')
        cookie = next(iter(browser.jar))
        self.assertIn('HttpOnly', cookie._rest)
        self.assertEqual(cookie._rest['SameSite'], 'Strict')
        self.assertEqual(browser.request('/api/clients', {'alias':'no','tax_year':2025}, {'X-Local-Token':''})[0],403)
        self.assertEqual(browser.request('/api/clients', {'alias':'no','tax_year':2025}, {'Origin':'https://evil.example'})[0],403)
        self.assertEqual(browser.request('/api/clients', headers={'Host':'evil.example'})[0],403)
        self.assertEqual(browser.request('/api/login', {'username':'alice','password':PASSWORD}, {'Origin':'https://evil.example'})[0],403)

    def test_reader_can_read_but_never_write_or_admin(self):
        editor, reader = self.browser('alice'), self.browser('reader')
        cid, workspace = self.demo(editor)
        self.assertEqual(reader.request('/api/workspace?client_id='+str(cid))[0],200)
        self.assertEqual(reader.request('/api/pages/'+str(workspace['pages'][0]['id'])+'/image')[0],200)
        for path in ['/api/clients','/api/demo','/api/upload?client_id='+str(cid),'/api/users',
                     '/api/pages/1/disposition','/api/records/1','/api/server-backup']:
            self.assertEqual(reader.request(path, {})[0],403,path)
        for path in ['/api/users','/api/server-events','/api/backup','/admin']:
            self.assertEqual(reader.request(path)[0],403,path)
        for path in ['/api/users','/api/server-events','/api/backup']:
            self.assertEqual(editor.request(path)[0],403,path)

    def test_two_editors_record_race_and_identity(self):
        alice, bob = self.browser('alice'), self.browser('bob')
        _, workspace = self.demo(alice)
        record = next(r for r in workspace['records'] if r['form_type']=='W-2')
        payload = dict(record, reviewer='forged-person', notes='race')
        path = '/api/records/'+str(record['id'])
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda browser: browser.request(path, payload)[0], [alice,bob]))
        self.assertEqual(sorted(results), [200,409])
        with app.connection() as db:
            saved = json.loads(db.execute('SELECT payload FROM records WHERE id=?',(record['id'],)).fetchone()[0])
        self.assertIn(saved['reviewer'], ('alice','bob'))
        self.assertEqual(alice.request(path,payload)[0],409)

    def test_page_revision_and_intake_revision_conflicts(self):
        alice, bob = self.browser('alice'), self.browser('bob')
        cid, workspace = self.demo(alice)
        page = workspace['pages'][0]
        path = f"/api/pages/{page['id']}/disposition"
        data = {'disposition':'included','reviewer':'forged','revision':page['revision']}
        self.assertEqual(alice.request(path,data)[0],200)
        self.assertEqual(bob.request(path,data)[0],409)
        status, saved, _ = bob.request('/api/pages/'+str(page['id']))
        self.assertEqual(saved['reviewer'],'alice')
        self.assertEqual(saved['revision'],page['revision']+1)
        data = dict(client_id=cid,label='Test W-2',owner='taxpayer',state='missing',notes='',reviewer='forged')
        status, created, _ = alice.request('/api/intake',data)
        self.assertEqual(status,200)
        data.update(id=created['id'],revision=0,state='received')
        self.assertEqual(bob.request('/api/intake',data)[0],200)
        self.assertEqual(alice.request('/api/intake',data)[0],409)

    def test_logout_revokes_cookie(self):
        browser = self.browser('alice')
        cookie = next(iter(browser.jar)).value
        self.assertEqual(browser.request('/api/logout',{})[0],200)
        self.assertEqual(browser.request('/api/clients',headers={'Cookie':'taxprep_session='+cookie})[0],401)

    def test_idle_and_absolute_expiry(self):
        for field, age in [('touched',accounts.IDLE_SECONDS+1),('created',accounts.SESSION_SECONDS+1)]:
            browser = self.browser('alice')
            with app.connection() as db:
                db.execute(f'UPDATE sessions SET {field}=? WHERE csrf=?',(time.time()-age,browser.csrf))
            self.assertEqual(browser.request('/api/clients')[0],401)

    def test_admin_accounts_disable_and_last_admin(self):
        admin = self.browser('admin')
        data = dict(username='temporary',role='editor',password=PASSWORD,active=True)
        self.assertEqual(admin.request('/api/users',data)[0],200)
        user = self.browser('temporary')
        data.update(password='',active=False)
        self.assertEqual(admin.request('/api/users',data)[0],200)
        self.assertEqual(user.request('/api/clients')[0],401)
        self.assertEqual(Browser(self.url).login('temporary')[0],401)
        self.assertEqual(admin.request('/api/users',dict(username='admin',role='viewer',active=True))[0],400)
        self.assertEqual(admin.request('/api/users',dict(username='admin',role='admin',active=False))[0],400)
        status, users, _ = admin.request('/api/users')
        self.assertEqual(status,200)
        self.assertNotIn('password_hash',json.dumps(users))

    def test_password_change_and_reset_revoke_existing_sessions(self):
        admin = self.browser('admin')
        data = dict(username='password-test',role='viewer',password=PASSWORD,active=True)
        self.assertEqual(admin.request('/api/users',data)[0],200)
        one, two = self.browser('password-test'), self.browser('password-test')
        self.assertEqual(one.request('/api/password',dict(old_password='wrong',password=PASSWORD+'new'))[0],400)
        self.assertEqual(one.request('/api/password',dict(old_password=PASSWORD,password=PASSWORD+'new'))[0],200)
        self.assertEqual(two.request('/api/clients')[0],401)
        self.assertEqual(Browser(self.url).login('password-test')[0],401)
        self.assertEqual(Browser(self.url).login('password-test',PASSWORD+'new')[0],200)

    def test_login_rate_limit_and_password_hashes(self):
        browser = Browser(self.url)
        for _ in range(10):
            self.assertEqual(browser.login('nonexistent','wrong')[0],401)
        self.assertEqual(browser.login('nonexistent','wrong')[0],429)
        with app.connection() as db:
            row = db.execute("SELECT password_hash FROM users WHERE username='alice'").fetchone()
        self.assertNotIn(PASSWORD,row[0])
        self.assertTrue(accounts.verify_password(PASSWORD,row[0]))

    def test_server_backup_restore_keeps_users_and_history(self):
        admin = self.browser('admin')
        self.demo(admin)
        status, result, _ = admin.request('/api/server-backup',{})
        self.assertEqual(status,200)
        backup = app.DATA/'backups'/result['filename']
        self.assertTrue(backup.is_file())
        restored = Path(self.temp.name)/'restored'
        report = restore(backup,restored)
        self.assertGreater(report['clients'],0)
        with app.sqlite3.connect(restored/'taxprep.sqlite3',factory=app.ClosingConnection) as db:
            db.row_factory = app.sqlite3.Row
            self.assertEqual(db.execute("SELECT role FROM users WHERE username='admin'").fetchone()[0],'admin')
            self.assertGreater(db.execute('SELECT COUNT(*) FROM server_events').fetchone()[0],0)
        status, events, _ = admin.request('/api/server-events')
        self.assertEqual(status,200)
        self.assertTrue(any(e['username']=='admin' and e['action']=='write' for e in events))

    def test_existing_schema_upgrade_preserves_pages(self):
        # Migrations are additive; re-initialization retains revision values and content.
        admin = self.browser('admin')
        _, workspace = self.demo(admin)
        page_id = workspace['pages'][0]['id']
        with app.connection() as db:
            before = dict(db.execute('SELECT * FROM pages WHERE id=?',(page_id,)).fetchone())
        app.init_db()
        with app.connection() as db:
            after = dict(db.execute('SELECT * FROM pages WHERE id=?',(page_id,)).fetchone())
        self.assertEqual(before,after)


if __name__ == '__main__':
    unittest.main()
