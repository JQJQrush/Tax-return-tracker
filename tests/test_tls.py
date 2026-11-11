"""Real TLS requests with a temporary, explicitly trusted test certificate."""
import http.cookiejar
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from taxtracker.operations import accounts
import app
import server

OPENSSL = shutil.which('openssl')
if not OPENSSL and Path(r'C:\Program Files\Git\usr\bin\openssl.exe').is_file():
    OPENSSL = r'C:\Program Files\Git\usr\bin\openssl.exe'


@unittest.skipUnless(OPENSSL, 'OpenSSL is required for temporary test certificates')
class TLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cert, key = root/'cert.pem', root/'key.pem'
        subprocess.run([OPENSSL,'req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1',
                        '-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
        cls.old_data = app.DATA
        app.DATA = root/'data'
        app.init_db()
        with app.connection() as db:
            accounts.init(db)
            accounts.save_user(db,'tls-admin','admin','Synthetic-tls-password-2026')
        cls.http = server.OfficeServer(('127.0.0.1',0),server.Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert,key)
        cls.http.tls_context = context
        host = '127.0.0.1:'+str(cls.http.server_port)
        server.configure(cls.http,[host],True)
        cls.url = 'https://'+host
        cls.client_context = ssl.create_default_context(cafile=str(cert))
        cls.thread = threading.Thread(target=cls.http.serve_forever)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        app.DATA = cls.old_data
        cls.temp.cleanup()

    def test_real_https_cookie_and_authenticated_request(self):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.client_context),
                                            urllib.request.HTTPCookieProcessor(jar))
        request = urllib.request.Request(self.url+'/api/login',
                  data=json.dumps(dict(username='tls-admin',password='Synthetic-tls-password-2026')).encode(),
                  headers={'Content-Type':'application/json','Origin':self.url})
        with opener.open(request,timeout=10) as response:
            self.assertEqual(response.status,200)
            self.assertIn('; Secure',response.headers['Set-Cookie'])
        self.assertTrue(next(iter(jar)).secure)
        with opener.open(self.url+'/api/config',timeout=10) as response:
            data = json.load(response)
            self.assertEqual(data['user']['username'],'tls-admin')
        request = urllib.request.Request(self.url+'/api/login',data=b'{}',headers={'Origin':'http://127.0.0.1'})
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            opener.open(request,timeout=10)
        self.assertEqual(rejected.exception.code,403)

    def test_idle_tls_client_does_not_block_other_clients(self):
        idle = socket.create_connection(('127.0.0.1',self.http.server_port),timeout=5)
        try:
            with urllib.request.urlopen(self.url+'/login',context=self.client_context,timeout=5) as response:
                self.assertEqual(response.status,200)
        finally:
            idle.close()


if __name__ == '__main__':
    unittest.main()
