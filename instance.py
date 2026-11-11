"""Verify an existing localhost instance before reusing its browser URL."""
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

PRODUCT='TaxReturnTracker'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def active_url(directory):
    try:
        info=json.loads((Path(directory)/'server-instance.json').read_text(encoding='utf-8'))
        url=info['url'];parsed=urlparse(url)
        if parsed.scheme not in ('http','https') or parsed.hostname not in ('127.0.0.1','localhost','::1'):
            return None
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            return None
        nonce=info['instance_id']
        if not isinstance(nonce,str) or len(nonce)!=48:return None
        request=Request(url.rstrip('/')+'/api/instance')
        with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=2) as response:
            if response.status!=200:return None
            data=json.loads(response.read(4096))
        if data.get('product')==PRODUCT and data.get('instance_id')==nonce:return url
    except (OSError,ValueError,KeyError,TypeError):
        return None
    return None
