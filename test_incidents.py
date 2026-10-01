import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import miniapp as m
import incidents as i

class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db';m.init(self.path);self.db=m.connection(self.path)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def create(self,profile='anna',**extra):
        with self.db:return m.apply_mutation(self.db,profile,'/api/incidents',{'address':'Учебный адрес, 1','description':'Вымышленный сценарий проверки','training_ack':True,**extra})['incident_id']
    def test_private_even_from_manager(self):
        iid=self.create()
        self.assertEqual(len(i.listing(m,self.db,'anna')['incidents']),1)
        self.assertEqual(len(i.listing(m,self.db,'dispatcher')['incidents']),1)
        for profile in ('manager','boris'):
            self.assertEqual(i.listing(m,self.db,profile)['incidents'],[])
            with self.assertRaises(m.Denied):i.detail(m,self.db,profile,iid)
            with self.assertRaises(m.Denied),self.db:m.mutate(self.db,profile,'/api/incidents/comment',{'id':iid,'version':1,'note':'Попытка чтения'})
        self.assertNotIn('incidents',m.state(self.db,'manager',1))
    def test_history_conflict_close(self):
        iid=self.create()
        with self.db:m.mutate(self.db,'dispatcher','/api/incidents/update',{'id':iid,'version':1,'status':'clarify','note':'Уточните учебный адрес'})
        with self.assertRaises(ValueError),self.db:m.mutate(self.db,'dispatcher','/api/incidents/update',{'id':iid,'version':1,'status':'closed','note':'Устаревший ответ'})
        with self.db:m.mutate(self.db,'anna','/api/incidents/comment',{'id':iid,'version':2,'note':'Учебный адрес уточнён'})
        with self.assertRaises(m.Denied),self.db:m.mutate(self.db,'anna','/api/incidents/update',{'id':iid,'version':3,'status':'closed','note':'Попытка смены статуса'})
        with self.db:m.mutate(self.db,'dispatcher','/api/incidents/update',{'id':iid,'version':3,'status':'closed','note':'Учебный разбор завершён'})
        item=i.detail(m,self.db,'anna',iid)
        self.assertEqual(len(item['events']),4);self.assertEqual(item['version'],4)
        with self.assertRaises(ValueError),self.db:m.mutate(self.db,'anna','/api/incidents/comment',{'id':iid,'version':4,'note':'После завершения'})
    def test_retry_and_training_ack(self):
        a=self.create(request_id='incident-retry-0001');b=self.create(request_id='incident-retry-0001');self.assertEqual(a,b)
        with self.assertRaises(ValueError):self.create(training_ack=False)
        self.assertEqual(self.db.execute('SELECT count(*) FROM incidents').fetchone()[0],1)
    def test_max_separate_role_and_disabled_default(self):
        with patch.object(m,'MODE','max'),patch.dict(os.environ,{'ADMIN_IDS':'99','DISPATCHER_IDS':'22','TRAINING_INCIDENTS_ENABLED':'0'}):
            with self.assertRaises(m.Denied):i.listing(m,self.db,'max:22')
            with patch.dict(os.environ,{'TRAINING_INCIDENTS_ENABLED':'1'}):
                iid=self.create('max:11')
                with self.assertRaises(m.Denied):i.detail(m,self.db,'max:99',iid)
                with self.db:m.mutate(self.db,'max:22','/api/incidents/update',{'id':iid,'version':1,'status':'review','note':'Секретное уточнение'})
                note=self.db.execute('SELECT text FROM app_outbox').fetchone()[0]
                self.assertNotIn('Секретное',note);self.assertNotIn('адрес',note)
                self.assertFalse(m.is_manager('max:22'))
