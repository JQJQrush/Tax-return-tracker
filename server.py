"""Authenticated, single-process office server. Run --help for setup."""
import argparse
import getpass
from http.cookies import SimpleCookie, CookieError
import json
from pathlib import Path
import secrets
import socket
import ssl
import threading
import webbrowser
from urllib.parse import urlparse

import accounts
import app

WRITE_LOCK = threading.RLock()


class AccessError(Exception):
    def __init__(self, message, status):
        self.message, self.status = message, status


class OfficeServer(app.ThreadingHTTPServer):
    daemon_threads = False
    request_queue_size = 32

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        self.tls_context = None
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(60)
        if self.tls_context:
            connection = self.tls_context.wrap_socket(connection, server_side=True, do_handshake_on_connect=False)
        return connection, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(app.Handler):
    server_version = 'TaxTracker/0.7'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def cookie_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            return cookie['taxprep_session'].value if 'taxprep_session' in cookie else ''
        except CookieError:
            return ''

    def send(self, value, status=200, content_type='application/json; charset=utf-8', extra=None):
        path = urlparse(self.path).path
        if path == '/api/config' and isinstance(value, dict) and status == 200:
            value = dict(value, version='0.7-server', user={k:self.user[k] for k in ('username','role')})
        if self.command == 'POST' and 200 <= status < 300 and getattr(self, 'user', None):
            with app.connection() as db:
                accounts.event(db, self.user['username'], 'write', path)
        headers = {'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
                   'Referrer-Policy': 'no-referrer', **(extra or {})}
        return super().send(value, status, content_type, headers)

    def guarded(self):
        host = self.headers.get('Host', '').lower()
        if host not in self.server.allowed_hosts:
            raise AccessError('服务器地址不在允许列表中', 403)
        origin = self.headers.get('Origin')
        expected = ('https' if self.server.secure else 'http') + '://' + host
        if origin and origin != expected:
            raise AccessError('拒绝跨站请求', 403)
        path = urlparse(self.path).path
        if path in ('/login', '/api/login'):
            return
        with app.connection() as db:
            self.user = accounts.session(db, self.cookie_token(), touch=self.command == 'POST')
        if not self.user:
            raise AccessError('请登录，或会话已过期', 401)
        if self.command == 'POST':
            if not secrets.compare_digest(self.headers.get('X-Local-Token', ''), self.user['csrf']):
                raise AccessError('会话验证失败，请刷新页面', 403)
            if path not in ('/api/logout', '/api/password') and self.user['role'] == 'viewer':
                raise AccessError('此账号只有查看权限', 403)
        if path in ('/admin', '/api/users', '/api/server-events', '/api/backup', '/api/server-backup') and self.user['role'] != 'admin':
            raise AccessError('此操作需要管理员权限', 403)

    def do_GET(self):
        try:
            self.guarded()
            path = urlparse(self.path).path
            if path == '/login':
                return self.send((app.ROOT/'login.html').read_bytes(), content_type='text/html; charset=utf-8')
            if path in ('/', '/admin'):
                filename = 'admin.html' if path == '/admin' else 'index.html'
                html = (app.ROOT/filename).read_text(encoding='utf-8').replace('__LOCAL_TOKEN__', self.user['csrf'])
                return self.send(html.encode(), content_type='text/html; charset=utf-8')
            if path == '/api/users':
                with app.connection() as db:
                    rows = [dict(r) for r in db.execute('SELECT username,role,active FROM users ORDER BY username')]
                return self.send(rows)
            if path == '/api/server-events':
                with app.connection() as db:
                    rows = [dict(r) for r in db.execute('SELECT * FROM server_events ORDER BY id DESC LIMIT 500')]
                return self.send(rows)
            return super().do_GET()
        except AccessError as exc:
            if exc.status == 401 and urlparse(self.path).path in ('/', '/admin'):
                return self.send(b'', 303, 'text/plain', {'Location':'/login'})
            self.send({'error':exc.message}, exc.status)

    def read_json(self):
        if self.headers.get('Transfer-Encoding'):
            raise AccessError('不支持此请求编码', 400)
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise AccessError('请求大小无效', 400)
        if not 0 < length <= 8192:
            raise AccessError('请求大小无效', 400)
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeError):
            raise AccessError('请求格式无效', 400)

    def do_POST(self):
        # Serialize writes before revision checks; OCR workers keep their own transactions.
        with WRITE_LOCK:
            try:
                self.guarded()
                path = urlparse(self.path).path
                if path == '/api/login':
                    data = self.read_json()
                    with app.connection() as db:
                        result, status = accounts.login(db, data.get('username',''), data.get('password',''), self.client_address[0])
                    if not result:
                        return self.send({'error':'登录尝试过多，请 15 分钟后重试' if status == 429 else '用户名或密码错误'}, status)
                    flag = '; Secure' if self.server.secure else ''
                    return self.send({'ok':True}, extra={'Set-Cookie':f"taxprep_session={result['token']}; HttpOnly; SameSite=Strict; Path=/; Max-Age={accounts.SESSION_SECONDS}{flag}"})
                if path == '/api/logout':
                    with app.connection() as db:
                        accounts.logout(db, self.cookie_token())
                    return self.send({'ok':True}, extra={'Set-Cookie':'taxprep_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' + ('; Secure' if self.server.secure else '')})
                if path == '/api/users':
                    data = self.read_json()
                    if not isinstance(data.get('active', True), bool):
                        raise ValueError('启用状态无效')
                    with app.connection() as db:
                        accounts.save_user(db, data.get('username',''), data.get('role'), data.get('password') or None,
                                           data.get('active',True), self.user['username'])
                    return self.send({'saved':True})
                if path == '/api/password':
                    data = self.read_json()
                    if not data.get('password'):
                        raise ValueError('请输入新密码')
                    with app.connection() as db:
                        row = db.execute('SELECT * FROM users WHERE id=?',(self.user['id'],)).fetchone()
                        if not accounts.verify_password(data.get('old_password',''), row['password_hash']):
                            raise AccessError('当前密码错误', 400)
                        accounts.save_user(db, row['username'], row['role'], data.get('password'), True, row['username'])
                    return self.send({'saved':True})
                if path == '/api/server-backup':
                    self.read_json()
                    directory = app.DATA/'backups'
                    directory.mkdir(exist_ok=True)
                    filename = 'taxprep-' + app.datetime.datetime.now(app.datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(4) + '.zip'
                    content = app.build_backup()
                    temporary = directory/(filename + '.tmp')
                    try:
                        temporary.write_bytes(content)
                        temporary.replace(directory/filename)
                    finally:
                        temporary.unlink(missing_ok=True)
                    return self.send({'filename':filename})
                if self.headers.get('Transfer-Encoding'):
                    raise AccessError('不支持此请求编码', 400)
                return super().do_POST()
            except AccessError as exc:
                self.send({'error':exc.message}, exc.status)
            except (ValueError, TypeError) as exc:
                self.send({'error':str(exc)}, 400)


def configure(server, hosts, secure):
    server.allowed_hosts = {h.lower() for h in hosts}
    server.secure = secure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True, help='Server-local data folder, outside the source checkout')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--allowed-host', action='append', default=[], help='Exact browser host:port; repeat as needed')
    parser.add_argument('--cert', type=Path, help='PEM certificate chain')
    parser.add_argument('--key', type=Path, help='PEM private key')
    parser.add_argument('--insecure-test-http', action='store_true', help='Synthetic-data LAN testing only')
    parser.add_argument('--set-user', help='Create/reset an account; password is prompted, never an argument')
    parser.add_argument('--role', choices=accounts.ROLES, default='admin')
    parser.add_argument('--open-browser', action='store_true')
    parser.add_argument('--setup-if-needed', action='store_true', help='Prompt for the first admin on the local console')
    args = parser.parse_args()
    app.DATA = args.data_dir.resolve()
    if str(app.DATA).startswith('\\\\'):
        parser.error('数据库必须放在服务器本机磁盘，不能使用网络共享')
    if app.DATA == app.ROOT or app.ROOT in app.DATA.parents:
        parser.error('资料目录必须位于程序目录之外，避免程序更新影响资料')
    lock = app.acquire_data_lock()
    server = None
    try:
        app.init_db()
        with app.connection() as db:
            accounts.init(db)
            # A restart/restore always requires a fresh login.
            db.execute('DELETE FROM sessions')
        with app.connection() as db:
            has_admin = bool(db.execute("SELECT 1 FROM users WHERE active=1 AND role='admin'").fetchone())
        if args.set_user or (args.setup_if_needed and not has_admin):
            username = args.set_user or 'admin'
            print('Create/reset app account: ' + username)
            password = getpass.getpass('Password (12+ characters): ')
            if password != getpass.getpass('Confirm password: '):
                parser.error('两次密码不一致')
            with app.connection() as db:
                accounts.save_user(db, username, args.role, password)
            print('Account saved. Start the server to log in.')
            if args.set_user:
                return
        with app.connection() as db:
            if not db.execute("SELECT 1 FROM users WHERE active=1 AND role='admin'").fetchone():
                parser.error('先使用 --set-user admin 创建管理员账号')
        if bool(args.cert) != bool(args.key):
            parser.error('--cert 和 --key 必须同时设置')
        secure = bool(args.cert)
        if args.host not in ('127.0.0.1','localhost','::1') and not secure and not args.insecure_test_http:
            parser.error('内网访问需要 HTTPS 证书；合成数据测试可显式使用 --insecure-test-http')
        if args.host not in ('127.0.0.1','localhost','::1') and not args.allowed_host:
            parser.error('请用 --allowed-host 指定员工浏览器访问的服务器名称或 IP 及端口')
        server = OfficeServer((args.host, args.port), Handler)
        configure(server, args.allowed_host or [f'localhost:{args.port}',f'127.0.0.1:{args.port}'], secure)
        if secure:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(args.cert, args.key)
            server.tls_context = context
        print('Tax Return Tracker 0.7 server — data: ' + str(app.DATA))
        print('Browser: ' + ('https' if secure else 'http') + '://' + sorted(server.allowed_hosts)[0])
        print('Keep this process running. Ctrl+C stops it; OCR jobs finish before shutdown.')
        if args.open_browser:
            webbrowser.open(('https' if secure else 'http') + '://' + sorted(server.allowed_hosts)[0])
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.server_close()
        app.POOL.shutdown(wait=True)
        lock.close()


if __name__ == '__main__':
    main()
