import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import miniapp as m


class OutageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db';m.init(self.path);self.db=m.connection(self.path)
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def create(self,**extra):
        with self.db:return m.mutate(self.db,'manager','/api/outages',{'house_ids':[1],'service':'water','title':'Отключение воды','reason':'Повреждение трубы','forecast':'Сегодня к 18:00',**extra})['outage_id']
    def test_shared_across_entrances_and_private_to_affected_houses(self):
        with self.db:other=m.mutate(self.db,'manager','/api/houses',{'name':'Другой дом','address':'Тестоград, Другая, 2','count':1})['entrance_id']
        oid=self.create()
        self.assertEqual(m.state(self.db,'anna',1)['outages'][0]['id'],oid)
        self.assertEqual(m.state(self.db,'boris',2)['outages'][0]['id'],oid)
        self.assertEqual(m.state(self.db,'manager',other)['outages'],[])
        with self.assertRaises(m.Denied):m.state(self.db,'anna',other)
        with self.assertRaises(m.Denied):m.mutate(self.db,'anna','/api/outages/update',{'id':oid,'status':'restored','version':1,'note':'Поддельное сообщение'})
    def test_history_conflict_and_restoration(self):
        oid=self.create()
        with self.db:m.mutate(self.db,'manager','/api/outages/update',{'id':oid,'version':1,'status':'work','note':'Бригада меняет участок','forecast':'Сегодня к 19:00'})
        with self.assertRaises(ValueError),self.db:m.mutate(self.db,'manager','/api/outages/update',{'id':oid,'version':1,'status':'work','note':'Устаревшее изменение'})
        with self.db:m.mutate(self.db,'manager','/api/outages/update',{'id':oid,'version':2,'status':'restored','note':'Подача воды восстановлена','forecast':'Ненужный прогноз'})
        row=m.state(self.db,'anna',1)['outages'][0]
        self.assertEqual(row['forecast'],'');self.assertEqual(row['version'],3)
        self.assertEqual(len(row['history']),3)
        self.assertEqual(row['history'][1]['forecast'],'Сегодня к 19:00')
    def test_invalid_house_list_leaves_no_outage(self):
        for houses in ([],[999],[True],'1'):
            with self.assertRaises(ValueError),self.db:self.create(house_ids=houses)
        self.assertEqual(self.db.execute('SELECT count(*) FROM outages').fetchone()[0],0)
    def test_retries_notify_each_resident_once(self):
        with self.db:
            self.db.executemany('INSERT INTO members(profile,entrance_id) VALUES(?,?)',[('max:11',1),('max:11',2),('max:22',3)])
        payload={'request_id':'outage-create-0001','house_ids':[1],'service':'power','title':'Нет электричества','reason':'Идёт проверка линии','forecast':''}
        with patch.object(m,'MODE','max'),patch.dict('os.environ',{'ADMIN_IDS':'99'}):
            with self.db:first=m.apply_mutation(self.db,'max:99','/api/outages',payload)
            with self.db:second=m.apply_mutation(self.db,'max:99','/api/outages',payload)
        self.assertEqual(first,second)
        self.assertEqual(self.db.execute('SELECT count(*) FROM app_outbox').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM outage_events').fetchone()[0],1)

if __name__=='__main__':unittest.main()
