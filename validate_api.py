"""Offline contract + real HTTP workflow on an isolated synthetic MAX server."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from contextlib import ExitStack
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from openapi_spec_validator import validate
from jsonschema import Draft202012Validator
import miniapp as m

ROOT=Path(__file__).resolve().parent
TOKEN='synthetic-contract-token-not-a-real-credential'
ORIGIN='https://contract.example.test'

def signed(uid):
    fields={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid,'first_name':'Учебный пользователь'},separators=(',',':'))}
    secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
    fields['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)

def main():
    spec=json.loads((ROOT/'openapi.json').read_text());validate(spec)
    fixture=json.loads((ROOT/'fixtures/scenario.json').read_text())
    seen=set()
    with ExitStack() as stack:
        folder=Path(stack.enter_context(tempfile.TemporaryDirectory()))
        dbpath=folder/'contract.sqlite3'
        stack.enter_context(patch.object(m,'MODE','max'))
        stack.enter_context(patch.object(m,'PUBLIC_ORIGIN',ORIGIN))
        stack.enter_context(patch.dict(os.environ,{'MAX_BOT_TOKEN':TOKEN,'ADMIN_IDS':'99','DISPATCHER_IDS':'22','TRAINING_INCIDENTS_ENABLED':'1','MAX_WEBHOOK_SECRET':'contract-webhook-secret'}))
        original=m.connection;m.init(dbpath)
        stack.enter_context(patch.object(m,'connection',lambda:original(dbpath)))
        server=ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def shutdown():server.shutdown();server.server_close();thread.join()
        stack.callback(shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        def request(path,body=None,uid=1,expected=200,headers=None):
            method='post' if body is not None else 'get';route=path.split('?')[0]
            hdr={'Host':'contract.example.test','Origin':ORIGIN,'X-Max-Init-Data':signed(uid),'Content-Type':'application/json',**(headers or {})}
            req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=hdr)
            try:response=urllib.request.urlopen(req,timeout=5)
            except urllib.error.HTTPError as exc:response=exc
            with response:
                code=response.status;value=json.load(response)
            assert code==expected,(method,route,code,value)
            operation=spec['paths'][route][method]
            schema=operation['responses'][str(code)]['content']['application/json']['schema']
            Draft202012Validator({'components':spec['components'],**schema}).validate(value)
            if code==200:seen.add((route,method))
            return value
        request('/health');request('/api/config')
        eid=request('/api/houses',fixture['house'],99)['entrance_id']
        manager=request('/api/state',uid=99);code=manager['entrances'][0]['code'];hid=manager['entrances'][0]['house_id']
        request('/api/join',{'code':code})
        request('/api/state?entrance_id='+str(eid),uid=2,expected=403)
        request('/api/messages',{'entrance_id':eid,'text':'Учебное сообщение'})
        tid=request('/api/tickets',{'entrance_id':eid,**fixture['ticket']})['ticket_id']
        request('/api/ticket?id='+str(tid))
        request('/api/queue',uid=99)
        request('/api/ticket/comment',{'entrance_id':eid,'id':tid,'text':'Учебное уточнение'})
        for status,uid in [('work',99),('done',99),('confirmed',1)]:request('/api/status',{'entrance_id':eid,'id':tid,'status':status},uid)
        request('/api/notices',{'entrance_id':eid,'title':'Учебное объявление','text':'Учебная проверка освещения','scope':'house'},99)
        nid=request('/api/state')['notices'][0]['id']
        request('/api/notice/read',{'entrance_id':eid,'id':nid})
        request('/api/invite/rotate',{'entrance_id':eid},99)
        oid=request('/api/outages',{'house_ids':[hid],**fixture['outage']},99)['outage_id']
        linked_tid=request('/api/tickets',{'entrance_id':eid,**fixture['ticket']})['ticket_id']
        request('/api/ticket/outage',{'entrance_id':eid,'id':linked_tid,'outage_id':oid})
        assert request('/api/ticket?id='+str(linked_tid))['outage']['id']==oid
        request('/api/outages/update',{'id':oid,'version':1,'status':'work','note':'Учебная бригада начала работу'},99)
        request('/api/outages/update',{'id':oid,'version':1,'status':'restored','note':'Устаревшее изменение'},99,400)
        payload={**fixture['incident'],'request_id':'contract-incident-001'}
        iid=request('/api/incidents',payload)['incident_id']
        assert request('/api/incidents',payload)['incident_id']==iid
        assert not request('/api/incidents',uid=99)['incidents']
        request('/api/incidents/update',{'id':iid,'version':1,'status':'review','note':'Учебный диспетчер начал разбор'},22)
        request('/api/incidents/comment',{'id':iid,'version':2,'note':'Автор уточняет учебные сведения'})
        request('/api/incidents/comment',{'id':iid,'version':3,'note':'Чужая попытка уточнения'},99,403)
        request('/api/incidents',uid=22)
        request('/api/state',expected=403,headers={'X-Max-Init-Data':'','X-Demo-Profile':'manager'})
        request('/api/messages',{'entrance_id':eid,'text':'Wrong origin'},expected=403,headers={'Origin':'https://foreign.example.test'})
        request('/webhook',{'update_type':'synthetic_test'},headers={'X-Max-Bot-Api-Secret':'contract-webhook-secret'})
        assert len(seen)==sum(len(v) for v in spec['paths'].values()),seen
        print(f'PASS: OpenAPI 3.1 valid; {len(seen)} HTTP operations, response schemas, role isolation, retry, version conflict, Origin and signed authentication')

if __name__=='__main__':main()
