"""Loopback-only server with explicit asset and export routes."""
import json
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .core import Error


STATIC = Path(__file__).resolve().parent.parent / 'static'


def make_server(store, port=8766):
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def allowed(self, write=False):
            host=self.headers.get('Host','')
            expected='127.0.0.1:%s'%self.server.server_port
            if host not in (expected,'localhost:%s'%self.server.server_port): return False
            origin=self.headers.get('Origin')
            if origin and origin not in ('http://'+expected,'http://localhost:%s'%self.server.server_port): return False
            if write and self.headers.get('X-Local-Token')!=token: return False
            return True
        def send(self,status,body,ctype='application/json; charset=utf-8'):
            if not isinstance(body,bytes): body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',ctype)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if not self.allowed(): return self.send(403,{'error':'只允许本机同源访问'})
            path=urlsplit(self.path).path
            if path=='/api/state': return self.send(200,dict(store.state(),csrf_token=token))
            if path.startswith('/api/file/'):
                bits=path.split('/')
                if len(bits)!=5 or bits[4] not in ('resume.txt','resume.pdf','source-map.json','cover-letter.txt','answers.json'): return self.send(404,{'error':'文件不存在'})
                with store.tx() as c:
                    row=c.execute('SELECT id FROM packages WHERE id=?',(bits[3],)).fetchone()
                if not row: return self.send(404,{'error':'材料版本不存在'})
                file=store.root/'packages'/bits[3]/bits[4]
                if not file.is_file(): return self.send(404,{'error':'文件不存在'})
                return self.send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            assets={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/styles.css':'styles.css','/style.css':'style.css'}
            if path in assets:
                file=STATIC/assets[path]
                if file.is_file(): return self.send(200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'text/plain')
            return self.send(404,{'error':'不存在的路由'})
        def do_POST(self):
            if not self.allowed(True): return self.send(403,{'error':'需要本机同源请求和会话令牌，请刷新页面'})
            if self.path not in ('/api/action', '/api/resume'): return self.send(404,{'error':'不存在的操作入口'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': return self.send(415,{'error':'只接受 JSON'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                maximum = 15 * 1024 * 1024 if self.path == '/api/resume' else 1024 * 1024
                if length<=0 or length>maximum: raise Error('请求超过允许大小；简历文件最大 10 MiB')
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict): raise Error('需要 JSON 对象')
                state=store.upload_resume(data) if self.path == '/api/resume' else store.action(data)
                return self.send(200,dict(state,csrf_token=token))
            except (Error,ValueError,KeyError,TypeError) as e:
                return self.send(400,{'error':str(e)})
            except Exception as e:
                return self.send(500,{'error':'操作未完成：'+str(e)})
        def do_OPTIONS(self): self.send(403,{'error':'不允许跨站访问'})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def periodic(store, stop):
    # A sleeping computer or exited process cannot run jobs; no launchd modification.
    while not stop.is_set():
        with store.tx() as c: cfg=store.meta(c,'config')
        if stop.wait(float(cfg['interval_minutes'])*60): break
        if store.is_running(): store.run()
