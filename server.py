#!/usr/bin/env python3
"""Wingman Review: small classroom QR survey and instructor results service.

Self-hosted informal recognition pilot. Set a strong admin password and a persistent
volume before exposing this application on the internet.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlparse
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE=Path(__file__).resolve().parent
RAILWAY_VOLUME=os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
ON_RAILWAY=bool(os.getenv('RAILWAY_PROJECT_ID'))
if ON_RAILWAY and not RAILWAY_VOLUME:
    raise SystemExit('ERROR: Add a persistent Railway volume at /data before running. Survey data must survive restarts.')
DATA=Path(RAILWAY_VOLUME if ON_RAILWAY else os.getenv('WINGMAN_DATA_DIR',str(BASE/'data')))
DATA.mkdir(parents=True,exist_ok=True)
PORT=int(os.getenv('PORT',os.getenv('WINGMAN_PORT','8765')))
BIND=os.getenv('WINGMAN_BIND','0.0.0.0' if ON_RAILWAY else '127.0.0.1')
RAILWAY_DOMAIN=os.getenv('RAILWAY_PUBLIC_DOMAIN','').strip()
PUBLIC_URL=os.getenv('WINGMAN_PUBLIC_URL',('https://'+RAILWAY_DOMAIN) if RAILWAY_DOMAIN else f'http://127.0.0.1:{PORT}').rstrip('/')
if ON_RAILWAY and not PUBLIC_URL.startswith('https://'):
    PUBLIC_URL='https://configure-your-railway-domain.invalid'

ADMIN_PASSWORD=os.getenv('WINGMAN_ADMIN_PASSWORD','')
if not ADMIN_PASSWORD or len(ADMIN_PASSWORD)<16:
    raise SystemExit('Set WINGMAN_ADMIN_PASSWORD to a unique strong password of at least 16 characters.')
# Secret persists between server restarts.
SECRET_PATH=DATA/'.secret'
if not SECRET_PATH.exists():
    fd=os.open(str(SECRET_PATH), os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as fh:fh.write(secrets.token_bytes(32))
SECRET=SECRET_PATH.read_bytes()
DB=DATA/'wingman.sqlite3'
RATING_IDS=['academic','duties','inclusivity','accountability','punctuality','appearance','integrity','fitness','focus','resilience','feedback','influence','communication','composure']


def conn():
    db=sqlite3.connect(DB,timeout=20)
    db.execute('PRAGMA busy_timeout=20000')
    return db

with conn() as db:
    db.execute('CREATE TABLE IF NOT EXISTS class_info (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS submissions (class_id TEXT NOT NULL, rater_id TEXT PRIMARY KEY, data TEXT NOT NULL, at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')


def get_config():
    with conn() as db:
        row=db.execute('SELECT data FROM class_info WHERE id=1').fetchone()
    return json.loads(row[0]) if row else None


def get_submissions():
    with conn() as db:
        rows=db.execute('SELECT rater_id, data, at FROM submissions').fetchall()
    return {rater:{'raterId':rater,'reviews':json.loads(data)['reviews'],'importedAt':at} for rater,data,at in rows}


def assigned(config,rater):
    ids=[r['id'] for r in config['roster']]
    if rater not in ids:return []
    count=len(ids)-1 if config['reviewsPerStudent']=='all' else min(len(ids)-1,int(config['reviewsPerStudent']))
    if count==len(ids)-1:return [i for i in ids if i!=rater]
    seed=2166136261
    for ch in config['id']:
        seed=((seed^ord(ch))*16777619)&0xFFFFFFFF
    for i in range(len(ids)-1,0,-1):
        seed=(seed*1664525+1013904223)&0xFFFFFFFF
        j=seed%(i+1)
        ids[i],ids[j]=ids[j],ids[i]
    start=ids.index(rater)
    targets={ids[(start+i+1)%len(ids)] for i in range(count)}
    return [r['id'] for r in config['roster'] if r['id'] in targets]


def access_code(config,rater):
    # Per-student, per-cohort code: no external identity information exposed.
    digest=hmac.new(SECRET,f'{config["id"]}:{rater}:student'.encode(),hashlib.sha256).digest()
    return base64.b32encode(digest).decode('ascii').rstrip('=')[:10]


def pack_token(config,rater):
    raw=f'{config["id"]}|{rater}|{int(time.time())+8*3600}|{secrets.token_hex(8)}'
    sig=hmac.new(SECRET,raw.encode(),hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode((raw+'|'+sig).encode()).decode().rstrip('=')


def unpack_token(token):
    try:
        raw=base64.urlsafe_b64decode(token+'='*((4-len(token)%4)%4)).decode()
        id_,rater,expiry,nonce,sig=raw.split('|')
        message='|'.join([id_,rater,expiry,nonce])
        expected=hmac.new(SECRET,message.encode(),hashlib.sha256).hexdigest()
        c=get_config()
        if c and hmac.compare_digest(expected,sig) and id_==c['id'] and int(expiry)>=time.time() and any(r['id']==rater for r in c['roster']):
            return rater
    except (ValueError,UnicodeDecodeError,OverflowError):pass
    return None


def validate_reviews(config, rater, reviews):
    required=set(assigned(config,rater))
    if not isinstance(reviews,list) or len(reviews)!=len(required):return 'Complete each assigned peer review before submitting.'
    seen=set()
    for item in reviews:
        if not isinstance(item,dict) or item.get('targetId') not in required or item['targetId'] in seen:return 'Invalid or duplicate peer review.'
        seen.add(item['targetId'])
        ratings=item.get('ratings')
        if not isinstance(ratings,dict) or set(ratings)!=set(RATING_IDS):return 'All 14 questions must be answered for each peer.'
        if any(not (type(v)==int and 1<=v<=5 or v=='NO') for v in ratings.values()):return 'Invalid rating value.'
        for key in ('leadership','blindspot'):
            if not isinstance(item.get(key,''),str) or len(item.get(key,''))>1500:return 'Invalid written response.'
    return None


class Handler(BaseHTTPRequestHandler):
    server_version='WingmanPreview/2.0'
    def log_message(self,format_,*args):
        # Avoid logging personal review content; default access logs still include path and IP.
        print(f'{format_%args}')
    def send_headers(self,status=200,content_type='application/json; charset=utf-8',extra=None):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'; base-uri 'none'")
        if extra:
            for k,v in extra.items():self.send_header(k,v)
        self.end_headers()
    def send_json(self,body,status=200,extra=None):
        bs=json.dumps(body,ensure_ascii=False).encode('utf-8')
        self.send_headers(status,extra=extra)
        self.wfile.write(bs)
    def fail(self,detail,status=400):self.send_json({'error':detail},status)
    def admin(self):
        value=self.headers.get('Authorization','')
        try:
            if not value.startswith('Basic '):return False
            credentials=base64.b64decode(value[6:]).decode('utf-8')
            username,password=credentials.split(':',1)
            return hmac.compare_digest(username,'instructor') and hmac.compare_digest(password,ADMIN_PASSWORD)
        except Exception:return False
    def need_admin(self):
        if self.admin():return True
        self.send_json({'error':'Instructor sign-in required'},401,{'WWW-Authenticate':'Basic realm="Wingman Instructor Portal", charset="UTF-8"'})
        return False
    def get_token(self):
        cookies=SimpleCookie()
        try:cookies.load(self.headers.get('Cookie',''))
        except Exception:return None
        return unpack_token(cookies['wingman_session'].value) if 'wingman_session' in cookies else None
    def json_body(self):
        if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':raise ValueError('JSON content type required')
        size=int(self.headers.get('Content-Length','0'))
        if size<=0 or size>180000:raise ValueError('Request too large or empty')
        return json.loads(self.rfile.read(size))
    def cookie_header(self,value,max_age=28800):
        sec='; Secure' if PUBLIC_URL.startswith('https://') else ''
        return f'wingman_session={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{sec}'
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/':
            self.send_response(302);self.send_header('Location','/student');self.end_headers();return
        if path=='/favicon.ico':self.send_headers(204);return
        if path=='/healthz':return self.send_json({'ok':True})
        if path=='/student':return self.static('student.html')
        if path=='/admin':
            if self.need_admin():return self.static('admin.html')
            return
        if path=='/api/class':
            c=get_config()
            return self.send_json({'config':c})
        if path=='/api/me':
            r=self.get_token()
            return self.send_json({'raterId':r,'submitted':bool(r and r in get_submissions())})
        if path=='/api/admin/overview':
            if not self.need_admin():return
            c=get_config()
            codes=[{'name':r['name'],'id':r['id'],'code':access_code(c,r['id'])} for r in c['roster']] if c else []
            return self.send_json({'config':c,'received':get_submissions(),'codes':codes,'studentUrl':PUBLIC_URL+'/student'})
        if path=='/api/admin/qr.svg':
            if not self.need_admin():return
            try:
                import qrcode
                import qrcode.image.svg
                img=qrcode.make(PUBLIC_URL+'/student',image_factory=qrcode.image.svg.SvgPathImage,box_size=8,border=3)
                stream=io.BytesIO();img.save(stream)
                self.send_headers(200,'image/svg+xml')
                self.wfile.write(stream.getvalue())
            except ImportError:return self.fail('Install qrcode to render the QR image.',503)
            return
        return self.fail('Not found',404)
    def static(self,name):
        content=(BASE/name).read_bytes()
        self.send_headers(200,'text/html; charset=utf-8')
        self.wfile.write(content)
    def do_POST(self):
        path=urlparse(self.path).path
        try:body=self.json_body()
        except (ValueError,json.JSONDecodeError,OverflowError) as e:return self.fail(str(e),400)
        if not isinstance(body,dict):return self.fail('Expected a JSON object.',400)
        if path=='/api/admin/config':
            if not self.need_admin():return
            title=body.get('title');names=body.get('names');count=body.get('reviewsPerStudent')
            if not isinstance(title,str) or not 1<=len(title.strip())<=120 or not isinstance(names,list) or not 4<=len(names)<=25 or not all(isinstance(n,str) and 1<=len(n.strip())<=100 for n in names):return self.fail('Supply a class name and 4–25 student names.')
            normalized=[n.strip() for n in names]
            if len({n.casefold() for n in normalized})!=len(normalized):return self.fail('Student names must be unique.')
            if count!='all' and (type(count)!=int or count not in (3,5,8)):return self.fail('Invalid assignment count.')
            old=get_config()
            unchanged=old and [r['name'] for r in old['roster']]==normalized and old['reviewsPerStudent']==count
            c={'type':'wingman-class-v1','version':1,'id':old['id'] if unchanged else secrets.token_hex(16),'title':title.strip(),'reviewsPerStudent':count,'roster':[{'id':f's{i+1}','name':name} for i,name in enumerate(normalized)]}
            with conn() as db:
                db.execute('INSERT OR REPLACE INTO class_info (id,data) VALUES (1,?)',(json.dumps(c),))
                if not unchanged:db.execute('DELETE FROM submissions')
            return self.send_json({'config':c,'reset':not unchanged})
        if path=='/api/student/login':
            c=get_config()
            if not c:return self.fail('This class is not open for reviews yet.',409)
            rater=body.get('raterId');code=str(body.get('code','')).replace(' ','').upper()
            if not isinstance(rater,str) or not any(r['id']==rater for r in c['roster']) or not hmac.compare_digest(code,access_code(c,rater)):
                return self.fail('Name and access code do not match. Ask your instructor to confirm your code.',403)
            if rater in get_submissions():return self.fail('This reviewer has already submitted.',409)
            return self.send_json({'ok':True,'raterId':rater},extra={'Set-Cookie':self.cookie_header(pack_token(c,rater))})
        if path=='/api/student/logout':
            return self.send_json({'ok':True},extra={'Set-Cookie':self.cookie_header('',0)})
        if path=='/api/student/submit':
            rater=self.get_token()
            if not rater:return self.fail('Sign in again before submitting.',401)
            c=get_config()
            why=validate_reviews(c,rater,body.get('reviews'))
            if why:return self.fail(why,400)
            record={'reviews':body['reviews']}
            try:
                with conn() as db:
                    db.execute('INSERT INTO submissions (class_id,rater_id,data) VALUES (?,?,?)',(c['id'],rater,json.dumps(record,ensure_ascii=False)))
            except sqlite3.IntegrityError:return self.fail('Your response has already been submitted.',409)
            return self.send_json({'ok':True,'reviewCount':len(body['reviews'])})
        return self.fail('Not found',404)


if __name__=='__main__':
    print(f'Wingman QR prototype listening at http://{BIND}:{PORT}')
    print('Instructor: /admin | Student: /student')
    print('Informal recognition pilot only: minimize student information and manage access codes privately.')
    ThreadingHTTPServer((BIND,PORT),Handler).serve_forever()
