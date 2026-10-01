import tempfile
import unittest
from pathlib import Path
from miniapp import init, connection, state, mutate, ticket_detail, manager_queue, apply_mutation, Denied


class MiniappTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.sqlite3'
        init(self.path)
        self.db = connection(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_entrance_isolation(self):
        self.assertEqual([e['id'] for e in state(self.db,'anna')['entrances']], [1])
        self.assertEqual([e['id'] for e in state(self.db,'boris')['entrances']], [2])
        with self.assertRaises(Denied): state(self.db,'boris',1)
        with self.assertRaises(Denied): mutate(self.db,'boris','/api/messages',{'entrance_id':1,'text':'Чужой подъезд'})

    def test_create_house_and_join(self):
        with self.db:
            result=mutate(self.db,'manager','/api/houses',{'name':'Тестовый дом','address':'Тестоград, Тестовая, 2','count':2})
        eid=result['entrance_id']
        self.assertEqual(len(state(self.db,'manager')['entrances']),5)
        with self.assertRaises(Denied): state(self.db,'anna',eid)
        code=self.db.execute('SELECT code FROM entrances WHERE id=?',(eid,)).fetchone()[0]
        with self.db:
            mutate(self.db,'anna','/api/join',{'code':code})
            mutate(self.db,'anna','/api/join',{'code':code})
            mutate(self.db,'anna','/api/messages',{'entrance_id':eid,'text':'Привет новому дому!'})
        self.assertEqual(len(state(self.db,'anna',eid)['members']),1)
        self.assertEqual(state(self.db,'manager',eid)['messages'][0]['text'],'Привет новому дому!')

    def test_resident_cannot_manage(self):
        with self.assertRaises(Denied): mutate(self.db,'anna','/api/houses',{'name':'Дом','address':'Адрес, 1','count':1})
        with self.assertRaises(Denied): mutate(self.db,'anna','/api/notices',{'entrance_id':1,'title':'Объявление','text':'Не от управляющей компании'})
        self.assertNotIn('code',state(self.db,'anna')['entrances'][0])

    def test_ticket_lifecycle(self):
        with self.assertRaises(Denied): mutate(self.db,'boris','/api/status',{'entrance_id':1,'id':1,'status':'done'})
        with self.db: mutate(self.db,'manager','/api/status',{'entrance_id':1,'id':1,'status':'done'})
        with self.assertRaises(Denied): mutate(self.db,'manager','/api/status',{'entrance_id':1,'id':1,'status':'confirmed'})
        with self.db: mutate(self.db,'anna','/api/status',{'entrance_id':1,'id':1,'status':'confirmed'})
        self.assertEqual(state(self.db,'anna')['tickets'][0]['status'],'confirmed')

    def test_invalid_invitation_and_house(self):
        with self.assertRaises(ValueError): mutate(self.db,'anna','/api/join',{'code':'MISSING'})
        with self.assertRaises(ValueError): mutate(self.db,'manager','/api/houses',{'name':'Дом','address':'Адрес, 1','count':99})
        self.assertEqual(len(state(self.db,'manager')['entrances']),3)

    def test_rotate_invitation_revokes_old_code_preserves_members(self):
        with self.assertRaises(Denied):
            mutate(self.db,'anna','/api/invite/rotate',{'entrance_id':1})
        with self.db:
            result=mutate(self.db,'manager','/api/invite/rotate',{'entrance_id':1})
        self.assertNotEqual(result['code'],'PARK-01')
        with self.assertRaises(ValueError):
            mutate(self.db,'boris','/api/join',{'code':'PARK-01'})
        self.assertEqual(state(self.db,'anna',1)['selected'],1)
        with self.db:
            mutate(self.db,'boris','/api/join',{'code':result['code']})
        self.assertEqual(state(self.db,'boris',1)['selected'],1)
        self.assertEqual(self.db.execute('SELECT code FROM entrances WHERE id=2').fetchone()[0],'PARK-02')

    def test_ticket_history_comments_and_reopening(self):
        with self.db:
            tid=mutate(self.db,'anna','/api/tickets',{'entrance_id':1,'title':'Лампа у лифта','category':'light','details':'Третий этаж, возле двери'})['ticket_id']
            mutate(self.db,'manager','/api/status',{'entrance_id':1,'id':tid,'status':'work'})
            mutate(self.db,'manager','/api/ticket/comment',{'entrance_id':1,'id':tid,'text':'Мастер придёт сегодня'})
            mutate(self.db,'manager','/api/status',{'entrance_id':1,'id':tid,'status':'done','note':'Лампа заменена'})
            mutate(self.db,'anna','/api/status',{'entrance_id':1,'id':tid,'status':'work','note':'На третьем этаже всё ещё темно'})
        detail=ticket_detail(self.db,'anna',tid)
        self.assertEqual(detail['ticket']['category'],'light')
        self.assertEqual(detail['ticket']['details'],'Третий этаж, возле двери')
        self.assertEqual([e['kind'] for e in detail['events']],['created','status','comment','status','status'])
        self.assertEqual(detail['events'][-1]['author'],'anna')
        self.assertEqual(detail['events'][-1]['text'],'На третьем этаже всё ещё темно')
        with self.assertRaises(Denied): ticket_detail(self.db,'boris',tid)
        with self.assertRaises(Denied): mutate(self.db,'boris','/api/ticket/comment',{'entrance_id':1,'id':tid,'text':'Чужая заявка'})
        with self.assertRaises(ValueError): mutate(self.db,'manager','/api/ticket/comment',{'entrance_id':2,'id':tid,'text':'Неверный подъезд'})

    def test_invalid_ticket_payload_does_not_create_ticket(self):
        for extra in [{'category':[]},{'category':'unknown'},{'details':42},{'details':'a'*2001}]:
            with self.assertRaises(ValueError), self.db:
                mutate(self.db,'anna','/api/tickets',{'entrance_id':1,'title':'Тестовая заявка',**extra})
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0],1)

    def test_migration_is_repeatable_and_preserves_old_tickets(self):
        old=Path(self.tmp.name)/'old.db'
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(old)) as db, db:
            db.executescript("CREATE TABLE tickets(id INTEGER PRIMARY KEY,entrance_id INTEGER,author TEXT,title TEXT,status TEXT DEFAULT 'new',created TEXT DEFAULT CURRENT_TIMESTAMP); INSERT INTO tickets(id,entrance_id,author,title) VALUES(10,1,'anna','Старая заявка');")
        init(old);init(old)
        db=connection(old)
        try:
            row=db.execute('SELECT * FROM tickets WHERE id=10').fetchone()
            self.assertEqual(row['title'],'Старая заявка')
            self.assertEqual(row['category'],'other')
            self.assertEqual(row['details'],'')
        finally: db.close()

    def test_manager_queue_covers_houses_and_rejects_resident(self):
        with self.db:
            mutate(self.db,'boris','/api/tickets',{'entrance_id':2,'title':'Вторая тестовая проблема'})
        queue=manager_queue(self.db,'manager')
        self.assertEqual({t['entrance_id'] for t in queue['tickets']},{1,2})
        self.assertEqual(queue['tickets'][0]['status'],'new')
        self.assertEqual(queue['counts']['work'],1)
        with self.assertRaises(Denied): manager_queue(self.db,'anna')

    def test_network_retry_creates_only_one_ticket(self):
        body={'request_id':'test-request-0001','entrance_id':1,'title':'Повтор при разрыве связи'}
        with self.db: first=apply_mutation(self.db,'anna','/api/tickets',body)
        with self.db: second=apply_mutation(self.db,'anna','/api/tickets',body)
        self.assertEqual(first,second)
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0],2)
        with self.assertRaises(ValueError), self.db:
            apply_mutation(self.db,'anna','/api/tickets',{**body,'title':'Иная заявка с тем же ключом'})
        self.assertEqual(len(ticket_detail(self.db,'anna',first['ticket_id'])['events']),1)

    def test_house_notice_and_read_receipts_are_isolated(self):
        with self.db:
            other=mutate(self.db,'manager','/api/houses',{'name':'Другой дом','address':'Тестоград, Лесная, 4','count':1})['entrance_id']
            result=mutate(self.db,'manager','/api/notices',{'entrance_id':1,'scope':'house','title':'Проверка воды','text':'Завтра проверяем воду во всём доме'})
        self.assertEqual(result['entrances'],3)
        self.assertEqual(state(self.db,'manager',other)['notices'],[])
        notice=state(self.db,'anna',1)['notices'][0]
        with self.db:
            mutate(self.db,'anna','/api/notice/read',{'entrance_id':1,'id':notice['id']})
            mutate(self.db,'anna','/api/notice/read',{'entrance_id':1,'id':notice['id']})
        self.assertEqual(state(self.db,'manager',1)['notices'][0]['read_count'],1)
        self.assertTrue(state(self.db,'anna',1)['notices'][0]['acknowledged'])
        self.assertEqual(state(self.db,'boris',2)['notices'][0]['read_count'],0)
        with self.assertRaises(Denied): mutate(self.db,'boris','/api/notice/read',{'entrance_id':1,'id':notice['id']})
        with self.assertRaises(ValueError): mutate(self.db,'boris','/api/notice/read',{'entrance_id':2,'id':notice['id']})
        with self.assertRaises(Denied): mutate(self.db,'anna','/api/notices',{'entrance_id':1,'scope':'house','title':'Подмена','text':'Подмена от жителя'})

    def test_persistence(self):
        with self.db: mutate(self.db,'anna','/api/messages',{'entrance_id':1,'text':'Проверка сохранения'})
        other=connection(self.path)
        self.assertEqual(state(other,'anna')['messages'][-1]['text'],'Проверка сохранения')
        other.close()


if __name__=='__main__': unittest.main()


class ConcurrentInitializationTests(unittest.TestCase):
    def test_simultaneous_startup_migrates_and_seeds_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'concurrent.db'
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(init,path) for _ in range(4)]
                for future in futures:future.result()
            db=connection(path)
            try:
                self.assertEqual(db.execute('SELECT count(*) FROM houses').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT count(*) FROM entrances').fetchone()[0],3)
                self.assertIn('details',{r['name'] for r in db.execute('PRAGMA table_info(tickets)')})
            finally:db.close()
