import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
import bot
import miniapp


class ConnectedBotTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        tmp=self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path=Path(tmp)/'shared.sqlite3'
        self.stack.enter_context(patch.dict(os.environ,{'APP_MODE':'max','ADMIN_IDS':'99','MINIAPP_ENABLED':'0'}))
        self.stack.enter_context(patch.object(miniapp,'MODE','max'))
        miniapp.init(self.path)
        original=miniapp.connection
        self.stack.enter_context(patch.object(miniapp,'connection',lambda:original(self.path)))
        self.db=bot.connect(':memory:')
        self.shared=miniapp.connection()
        self.seq=0
    def tearDown(self):
        self.shared.close();self.db.close();self.stack.close()
    def say(self,text,uid=1,key=None):
        self.seq+=1
        with self.db:bot.handle(self.db,uid,text,{99},key or f'event-{self.seq}')
        return json.loads(self.db.execute('SELECT body FROM outbox ORDER BY id DESC LIMIT 1').fetchone()[0])['text']
    def house(self):
        for text in ['Добавить дом','Дом у парка','Тестоград, Парковая, 5','2','Создать дом']:self.say(text,99)
        row=self.shared.execute('SELECT * FROM entrances ORDER BY id').fetchone()
        self.say('Вступить по коду');self.say(row['code'])
        return row['id']
    def ticket(self):
        for text in ['Новая заявка','Освещение','Лампа на третьем этаже не горит','Подтвердить заявку']:self.say(text)
        return self.shared.execute('SELECT id FROM tickets').fetchone()[0]
    def test_full_flow_shared_with_miniapp(self):
        eid=self.house();tid=self.ticket()
        self.assertEqual(miniapp.state(self.shared,'max:99',eid)['tickets'][0]['id'],tid)
        self.say(f'/status {tid} work',99)
        self.say(f'/comment {tid} Уже выехали',99)
        self.say(f'/status {tid} done',99)
        self.say(f'/confirm {tid}')
        detail=miniapp.ticket_detail(self.shared,'max:1',tid)
        self.assertEqual(detail['ticket']['status'],'confirmed')
        self.assertEqual(len(detail['events']),5)
        self.assertIn('Уже выехали',self.say(f'/ticket {tid}'))
    def test_access_control_and_emergency(self):
        self.house();tid=self.ticket()
        self.assertIn('недоступен',self.say(f'/ticket {tid}',2))
        self.assertIn('только УК',self.say('Добавить дом',2))
        self.assertIn('только УК',self.say('/queue',2))
        self.assertIn('112',self.say('Пахнет газом'))
        self.assertEqual(self.shared.execute('SELECT count(*) FROM tickets').fetchone()[0],1)
    def test_replay_after_outbox_transaction_failure(self):
        self.house()
        for text in ['Новая заявка','Освещение','Проверка повторной отправки']:self.say(text)
        self.say('Подтвердить заявку',key='same-confirmation')
        self.say('Подтвердить заявку',key='same-confirmation')
        self.assertEqual(self.shared.execute('SELECT count(*) FROM tickets').fetchone()[0],1)
        self.assertIn('№1',self.say('Подтвердить заявку',key='same-confirmation'))
    def test_invalid_house_count_retains_draft(self):
        for text in ['Добавить дом','Дом у парка','Тестоград, Парковая, 5']:self.say(text,99)
        self.assertIn('число',self.say('много',99))
        self.say('2',99);self.say('что дальше?',99)
        self.assertEqual(self.shared.execute('SELECT count(*) FROM houses').fetchone()[0],0)
        self.say('Создать дом',99)
        self.assertEqual(self.shared.execute('SELECT count(*) FROM entrances').fetchone()[0],2)
    def test_outages_use_shared_data(self):
        self.house()
        with self.shared:
            miniapp.mutate(self.shared,'max:99','/api/outages',{'house_ids':[1],'service':'water','title':'Проверка аварии воды','reason':'Повреждение трубопровода','forecast':'Сегодня к 18:00'})
        message=self.say('Аварии дома')
        self.assertIn('Проверка аварии воды',message)
        self.assertIn('Сегодня к 18:00',message)
        self.assertIn('УК в Домовом',message)
        self.assertNotIn('Проверка аварии воды',self.say('Аварии дома',2))

    def test_select_shared_outage_before_ticket_confirmation(self):
        self.house()
        with self.shared:
            oid=miniapp.mutate(self.shared,'max:99','/api/outages',{'house_ids':[1],'service':'water','title':'Авария подачи воды','reason':'Учебное повреждение трубы'})['outage_id']
        for text in ['Новая заявка','Вода и отопление','Нет холодной воды в квартире']:reply=self.say(text)
        self.assertIn('Авария подачи воды',reply)
        self.say(f'Связать с аварией №{oid}')
        self.say('Подтвердить заявку',key='linked-ticket-confirm')
        self.say('Подтвердить заявку',key='linked-ticket-confirm')
        self.assertEqual(self.shared.execute('SELECT count(*) FROM tickets').fetchone()[0],1)
        self.assertEqual(self.shared.execute('SELECT outage_id FROM tickets').fetchone()[0],oid)
        self.assertIn('Общая авария',self.say('/ticket 1'))

    def test_cancel_does_not_create_ticket(self):
        self.house();self.say('Новая заявка');self.say('Освещение');self.say('Лампа на площадке');self.say('Отмена');self.say('Подтвердить заявку')
        self.assertEqual(self.shared.execute('SELECT count(*) FROM tickets').fetchone()[0],0)


    def test_guided_work_report_reopen_and_comment(self):
        self.house();tid=self.ticket()
        self.say(f'Взять в работу №{tid}',99)
        self.assertIn('Расскажите',self.say(f'Работа выполнена №{tid}',99))
        self.say('Заменён выключатель, свет работает.',99)
        self.assertEqual(miniapp.ticket_detail(self.shared,'max:1',tid)['ticket']['status'],'done')
        self.assertIn('Что осталось',self.say(f'Проблема осталась №{tid}'))
        self.say('Свет снова погас на первом этаже.')
        self.assertEqual(miniapp.ticket_detail(self.shared,'max:1',tid)['ticket']['status'],'work')
        self.say(f'Комментарий к заявке №{tid}')
        self.say('Проверка комментария кнопкой',key='guided-comment-repeat')
        self.say('Проверка комментария кнопкой',key='guided-comment-repeat')
        events=miniapp.ticket_detail(self.shared,'max:1',tid)['events']
        self.assertEqual(sum(e['text']=='Проверка комментария кнопкой' for e in events),1)
        self.assertTrue(any(e['text']=='Заменён выключатель, свет работает.' for e in events))

    def test_guided_report_revalidates_changed_status(self):
        eid=self.house();tid=self.ticket()
        self.say(f'Взять в работу №{tid}',99)
        self.say(f'Работа выполнена №{tid}',99)
        with self.shared:miniapp.mutate(self.shared,'max:99','/api/status',{'entrance_id':eid,'id':tid,'status':'done','note':'Другой оператор завершил'})
        before=len(miniapp.ticket_detail(self.shared,'max:1',tid)['events'])
        self.say('Запоздалый отчёт',99)
        self.assertEqual(len(miniapp.ticket_detail(self.shared,'max:1',tid)['events']),before)
        self.assertIn('только УК',self.say(f'Работа выполнена №{tid}',1))

if __name__=='__main__':unittest.main()
