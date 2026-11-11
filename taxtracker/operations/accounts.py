"""Server-side accounts and revocable browser sessions. No external services."""
import hashlib
import hmac
import re
import secrets
import time

ROLES = ('admin', 'editor', 'viewer')
ITERATIONS = 600_000
IDLE_SECONDS = 30 * 60
SESSION_SECONDS = 12 * 60 * 60


def init(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS sessions(
      token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      csrf TEXT NOT NULL, created REAL NOT NULL, touched REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS login_limits(
      key TEXT PRIMARY KEY, started REAL NOT NULL, attempts INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS server_events(
      id INTEGER PRIMARY KEY, username TEXT NOT NULL, action TEXT NOT NULL,
      target TEXT NOT NULL, created REAL NOT NULL);
    ''')


def event(db, username, action, target=''):
    db.execute('INSERT INTO server_events(username,action,target,created) VALUES(?,?,?,?)',
               (username, action, target, time.time()))


def hash_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('密码需要 12–256 个字符')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'{ITERATIONS}${salt}${digest}'


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 256:
        return False
    rounds, salt, expected = encoded.split('$')
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
    return hmac.compare_digest(actual, expected)


def save_user(db, username, role, password=None, active=True, actor='console'):
    username = str(username).strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{1,63}', username) or role not in ROLES:
        raise ValueError('用户名需为 2–64 位英文字母、数字、点、下划线或短横线；请选择有效权限')
    row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    if row and row['role'] == 'admin' and row['active'] and (role != 'admin' or not active):
        if db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
            raise ValueError('必须保留至少一位启用的管理员')
    if not row and not password:
        raise ValueError('新员工必须设置密码')
    encoded = hash_password(password) if password else row['password_hash']
    if row:
        db.execute('UPDATE users SET password_hash=?,role=?,active=? WHERE id=?',
                   (encoded, role, int(active), row['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?', (row['id'],))
    else:
        db.execute('INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,?)',
                   (username, encoded, role, int(active)))
    event(db, actor, 'user_update', username)


def login(db, username, password, address):
    username = str(username).strip().lower()[:64]
    current = time.time()
    # Bound storage, and limit both the account and the actual peer IP (never forwarded headers).
    db.execute('DELETE FROM login_limits WHERE started<?', (current - 900,))
    keys = ('user:' + username, 'ip:' + address)
    for key in keys:
        row = db.execute('SELECT attempts FROM login_limits WHERE key=?', (key,)).fetchone()
        if row and row['attempts'] >= (10 if key.startswith('user:') else 40):
            return None, 429
    for key in keys:
        db.execute('INSERT INTO login_limits VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1',
                   (key, current))
    row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    # Equal-cost dummy hash keeps unknown usernames out of a fast failure path.
    encoded = row['password_hash'] if row else f'{ITERATIONS}$' + '00' * 16 + '$' + '00' * 32
    valid = verify_password(password, encoded)
    if not row or not valid or not row['active']:
        event(db, username, 'login_failed')
        return None, 401
    db.execute('DELETE FROM login_limits WHERE key=?', (keys[0],))
    db.execute('UPDATE login_limits SET attempts=MAX(0,attempts-1) WHERE key=?', (keys[1],))
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.execute('DELETE FROM sessions WHERE touched<? OR created<?',
               (current - IDLE_SECONDS, current - SESSION_SECONDS))
    db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',
               (hashlib.sha256(token.encode()).hexdigest(), row['id'], csrf, current, current))
    event(db, username, 'login')
    return {'token': token, 'csrf': csrf, 'username': username, 'role': row['role']}, 200


def session(db, token, touch=False):
    digest = hashlib.sha256(token.encode()).hexdigest()
    current = time.time()
    row = db.execute('''SELECT u.id,u.username,u.role,s.csrf,s.created,s.touched FROM sessions s
                        JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND u.active=1''', (digest,)).fetchone()
    if not row or row['touched'] < current - IDLE_SECONDS or row['created'] < current - SESSION_SECONDS:
        db.execute('DELETE FROM sessions WHERE token_hash=?', (digest,))
        return None
    if touch:
        db.execute('UPDATE sessions SET touched=? WHERE token_hash=?', (current, digest))
    return dict(row)


def logout(db, token):
    db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
