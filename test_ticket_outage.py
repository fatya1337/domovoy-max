import tempfile
import unittest
from pathlib import Path
import miniapp as m

class TicketOutageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'linked.db';m.init(self.path);self.db=m.connection(self.path)
        with self.db:self.oid=m.mutate(self.db,'manager','/api/outages',{'house_ids':[1],'service':'water','title':'Учебное отключение воды','reason':'Повреждён учебный участок'})['outage_id']
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def ticket(self,oid=None):
        with self.db:return m.mutate(self.db,'anna','/api/tickets',{'entrance_id':1,'title':'В квартире нет холодной воды','category':'water','outage_id':oid})['ticket_id']
    def test_linked_status_updates_without_closing_ticket(self):
        tid=self.ticket(self.oid)
        with self.db:m.mutate(self.db,'manager','/api/outages/update',{'id':self.oid,'version':1,'status':'restored','note':'Учебная подача восстановлена'})
        info=m.ticket_detail(self.db,'anna',tid)
        self.assertEqual(info['outage']['status'],'restored');self.assertEqual(info['ticket']['status'],'new')
        self.assertEqual(info['events'][-1]['kind'],'outage')
        self.assertEqual(self.db.execute('SELECT count(*) FROM app_outbox').fetchone()[0],0)
    def test_other_house_and_restored_rejected_before_ticket_creation(self):
        with self.db:
            eid=m.mutate(self.db,'manager','/api/houses',{'name':'Другой дом','address':'Тестоград, Другой адрес, 1','count':1})['entrance_id']
            hid=self.db.execute('SELECT house_id FROM entrances WHERE id=?',(eid,)).fetchone()[0]
            other=m.mutate(self.db,'manager','/api/outages',{'house_ids':[hid],'service':'power','title':'Чужая учебная авария','reason':'Проверка линии питания'})['outage_id']
        for bad in (other,999,True,'1'):
            with self.assertRaises(ValueError):self.ticket(bad)
        with self.db:m.mutate(self.db,'manager','/api/outages/update',{'id':self.oid,'version':1,'status':'restored','note':'Учебная подача восстановлена'})
        with self.assertRaises(ValueError):self.ticket(self.oid)
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0],1)
    def test_only_author_or_manager_can_change_link_and_retry_is_safe(self):
        tid=self.ticket()
        with self.db:self.db.execute("INSERT INTO members VALUES('boris',1)")
        payload={'entrance_id':1,'id':tid,'outage_id':self.oid,'request_id':'link-outage-retry-001'}
        with self.assertRaises(m.Denied),self.db:m.apply_mutation(self.db,'boris','/api/ticket/outage',payload)
        with self.db:m.apply_mutation(self.db,'anna','/api/ticket/outage',payload)
        with self.db:m.apply_mutation(self.db,'anna','/api/ticket/outage',payload)
        self.assertEqual(len(m.ticket_detail(self.db,'anna',tid)['events']),2)
        with self.db:m.mutate(self.db,'manager','/api/ticket/outage',{'entrance_id':1,'id':tid,'outage_id':None})
        self.assertIsNone(m.ticket_detail(self.db,'anna',tid)['outage'])
    def test_link_remains_accessible_after_list_limit_and_confirmed_is_frozen(self):
        tid=self.ticket(self.oid)
        with self.db:
            for n in range(31):m.mutate(self.db,'manager','/api/outages',{'house_ids':[1],'service':'water','title':f'Новая учебная авария {n}','reason':'Проверка списка событий'})
            self.db.execute("UPDATE tickets SET status='confirmed' WHERE id=?",(tid,))
        self.assertNotIn(self.oid,[o['id'] for o in m.house_outages(self.db,'anna',1)])
        self.assertEqual(m.ticket_detail(self.db,'anna',tid)['outage']['id'],self.oid)
        with self.assertRaises(ValueError),self.db:m.mutate(self.db,'manager','/api/ticket/outage',{'entrance_id':1,'id':tid,'outage_id':None})

    def test_restored_link_can_be_kept_but_not_added_again(self):
        tid=self.ticket(self.oid)
        with self.db:m.mutate(self.db,'manager','/api/outages/update',{'id':self.oid,'version':1,'status':'restored','note':'Учебная подача восстановлена'})
        payload={'entrance_id':1,'id':tid,'outage_id':self.oid}
        with self.db:m.mutate(self.db,'anna','/api/ticket/outage',payload)
        self.assertEqual(len(m.ticket_detail(self.db,'anna',tid)['events']),2)
        with self.assertRaises(ValueError),self.db:m.mutate(self.db,'anna','/api/ticket/outage',{**payload,'outage_id':True})
        with self.db:m.mutate(self.db,'anna','/api/ticket/outage',{**payload,'outage_id':None})
        with self.assertRaises(ValueError),self.db:m.mutate(self.db,'anna','/api/ticket/outage',payload)
