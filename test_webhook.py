import http.client
import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import miniapp
import bot
import worker
from test_max_auth import TOKEN, signed
import time


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        tmp=self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path=Path(tmp)/'pilot.db'
        self.stack.enter_context(patch.object(miniapp,'MODE','max'))
        self.stack.enter_context(patch.object(miniapp,'PUBLIC_ORIGIN','https://app.example.test'))
        self.stack.enter_context(patch.dict('os.environ',{'MAX_BOT_TOKEN':TOKEN,'MAX_WEBHOOK_SECRET':'test-secret','ADMIN_IDS':'123','APP_MODE':'max'}))
        miniapp.init(self.path)
        original=miniapp.connection
        self.stack.enter_context(patch.object(miniapp,'connection',lambda: original(self.path)))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),miniapp.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.stack.close()

    def request(self,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        base={'Host':'app.example.test',**(headers or {})}
        if body is not None: base['Content-Type']='application/json'
        conn.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,base)
        response=conn.getresponse();status=response.status;data=json.loads(response.read());conn.close()
        return status,data

    def test_live_mode_rejects_demo_impersonation(self):
        status,_=self.request('/api/state',headers={'X-Demo-Profile':'manager'})
        self.assertEqual(status,403)
        status,data=self.request('/api/state',headers={'X-Max-Init-Data':signed(timestamp=int(time.time()))})
        self.assertEqual(status,200);self.assertEqual(data['profile']['role'],'manager');self.assertFalse(data['demo'])

    def test_origin_and_resident_permissions(self):
        auth={'X-Max-Init-Data':signed(uid=456,timestamp=int(time.time()))}
        body={'name':'Дом','address':'Тестовый адрес, 1','count':1}
        self.assertEqual(self.request('/api/houses',body,auth)[0],403)
        self.assertEqual(self.request('/api/houses',body,{**auth,'Origin':'https://app.example.test'})[0],403)

    def test_webhook_auth_and_dedup(self):
        event={'update_type':'bot_started','user':{'user_id':123},'timestamp':1}
        self.assertEqual(self.request('/webhook',event)[0],403)
        headers={'X-Max-Bot-Api-Secret':'test-secret'}
        self.assertEqual(self.request('/webhook',event,headers)[0],200)
        self.assertEqual(self.request('/webhook',event,headers)[0],200)
        db=miniapp.connection()
        self.assertEqual(db.execute('SELECT count(*) FROM bot_events').fetchone()[0],1);db.close()

    def test_house_to_resident_to_bot_notification(self):
        def headers(uid):
            return {'X-Max-Init-Data':signed(uid=uid,timestamp=int(time.time())),'Origin':'https://app.example.test'}
        def post(path,body,uid):
            code,data=self.request(path,body,headers(uid))
            self.assertEqual(code,200,data)
            return data
        eid=post('/api/houses',{'name':'Дом у парка','address':'Тестоград, Парковая, 5','count':2},123)['entrance_id']
        code,data=self.request('/api/state',headers=headers(123))
        self.assertEqual(code,200)
        invite=data['entrances'][0]['code']
        post('/api/join',{'code':invite},456)
        ticket_payload={'entrance_id':eid,'title':'Не горит свет в подъезде','request_id':'retry-create-ticket-0001'}
        first=post('/api/tickets',ticket_payload,456)
        retry=post('/api/tickets',ticket_payload,456)
        self.assertEqual(first,retry)
        code,queue=self.request('/api/queue',headers=headers(123))
        self.assertEqual(code,200)
        self.assertEqual(len(queue['tickets']),1)
        self.assertEqual(self.request('/api/queue',headers=headers(456))[0],403)
        post('/api/ticket/comment',{'entrance_id':eid,'id':1,'text':'Уточнение: третий этаж'},456)
        code,detail=self.request('/api/ticket?id=1',headers=headers(456))
        self.assertEqual(code,200)
        self.assertEqual(detail['events'][-1]['text'],'Уточнение: третий этаж')
        self.assertEqual(self.request('/api/ticket?id=1',headers=headers(789))[0],403)
        self.assertEqual(self.request('/api/ticket?id=1',headers={'X-Demo-Profile':'manager'})[0],403)
        post('/api/status',{'entrance_id':eid,'id':1,'status':'work'},123)
        post('/api/status',{'entrance_id':eid,'id':1,'status':'done'},123)
        event={'update_type':'message_created','message':{'sender':{'user_id':456},'recipient':{'chat_type':'dialog'},'body':{'mid':'full-flow','text':'Мои заявки'}}}
        self.assertEqual(self.request('/webhook',event,{'X-Max-Bot-Api-Secret':'test-secret'})[0],200)
        delivered=[]
        class FakeMAX:
            def request(self,method,path,query,body):
                delivered.append((query['user_id'],body['text']))
                return {'message':{}}
        db=bot.connect(':memory:')
        with patch.object(bot.time,'sleep'):
            worker.cycle(db,FakeMAX(),{123})
        self.assertEqual(len(delivered),3)
        self.assertTrue(all(uid==456 for uid,_ in delivered))
        self.assertTrue(any('Не горит свет' in text for _,text in delivered))
        self.assertTrue(any('Выполнена' in text for _,text in delivered))
        post('/api/status',{'entrance_id':eid,'id':1,'status':'confirmed'},456)
        self.assertEqual(self.request('/api/state?entrance_id='+str(eid),headers=headers(789))[0],403)
        db.close()


if __name__=='__main__': unittest.main()
