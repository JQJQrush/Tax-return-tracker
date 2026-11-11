import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from taxtracker.operations import instance
import server


class InstanceTests(unittest.TestCase):
    def test_second_launch_opens_verified_instance_before_initializing_db(self):
        with tempfile.TemporaryDirectory() as folder:
            previous=server.app.DATA
            try:
                with patch('sys.argv',['server.py','--data-dir',folder,'--open-browser']), \
                     patch('server.app.acquire_data_lock',side_effect=ValueError('locked')), \
                     patch('server.instance.active_url',return_value='http://127.0.0.1:8765'), \
                     patch('server.webbrowser.open') as browser,patch('server.app.init_db') as init:
                    server.main()
                    browser.assert_called_once_with('http://127.0.0.1:8765');init.assert_not_called()
            finally:server.app.DATA=previous

    def test_verified_identity_and_stale_marker(self):
        nonce='a'*48
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps({'product':instance.PRODUCT,'instance_id':nonce}).encode())
            def log_message(self,*args):pass
        http=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=http.serve_forever);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                marker=Path(folder)/'server-instance.json';url=f'http://127.0.0.1:{http.server_port}'
                marker.write_text(json.dumps({'url':url,'instance_id':nonce}))
                self.assertEqual(instance.active_url(folder),url)
                marker.write_text(json.dumps({'url':url,'instance_id':'b'*48}))
                self.assertIsNone(instance.active_url(folder))
                marker.write_text('{broken')
                self.assertIsNone(instance.active_url(folder))
        finally:http.shutdown();http.server_close();thread.join()

    def test_untrusted_urls_never_probed(self):
        with tempfile.TemporaryDirectory() as folder:
            for url in ['http://example.com','file:///test','http://localhost@evil.example','http://localhost/?secret=1']:
                (Path(folder)/'server-instance.json').write_text(json.dumps({'url':url,'instance_id':'a'*48}))
                with patch.object(instance,'build_opener') as opener:
                    self.assertIsNone(instance.active_url(folder));opener.assert_not_called()
