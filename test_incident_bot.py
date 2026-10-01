from unittest.mock import patch
import test_connected_bot as harness
import miniapp
import incidents

class IncidentBotTests(harness.ConnectedBotTests):
    # Reuse the isolated two-database harness, not its unrelated cases.
    test_full_flow_shared_with_miniapp=None
    test_access_control_and_emergency=None
    test_replay_after_outbox_transaction_failure=None
    test_invalid_house_count_retains_draft=None
    test_outages_use_shared_data=None
    test_cancel_does_not_create_ticket=None
    test_select_shared_outage_before_ticket_confirmation=None
    test_guided_work_report_reopen_and_comment = None
    test_guided_report_revalidates_changed_status = None
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict('os.environ',{'TRAINING_INCIDENTS_ENABLED':'1','DISPATCHER_IDS':'22'}))
    def draft(self):
        for text in ('Новое учебное обращение','Понимаю, это учебный режим','Тестоград, Учебная, 2','Вымышленная ситуация для учебной проверки'):
            self.say(text)
    def test_full_private_roundtrip_without_house(self):
        self.draft();self.say('Сохранить учебное обращение')
        self.assertEqual(self.shared.execute('SELECT count(*) FROM houses').fetchone()[0],0)
        self.assertIn('№1',self.say('/incidents',22))
        self.say('/incident_status 1 clarify',22);self.say('Уточните учебный адрес',22)
        self.assertIn('Нужно уточнение',self.say('/incident 1'))
        self.say('/incident_reply 1');self.say('Учебный адрес подтверждён')
        self.say('/incident_status 1 closed',22);self.say('Учебный разбор завершён',22)
        item=incidents.detail(miniapp,self.shared,'max:1',1)
        self.assertEqual(item['status'],'closed');self.assertEqual(len(item['events']),4)
        self.assertIn('недоступно',self.say('/incident 1',99))
        self.assertIn('недоступно',self.say('/incident 1',2))
    def test_creation_confirmation_replay_and_cancel(self):
        self.draft();self.say('Сохранить учебное обращение',key='incident-confirm-1');self.say('Сохранить учебное обращение',key='incident-confirm-1')
        self.assertEqual(self.shared.execute('SELECT count(*) FROM incidents').fetchone()[0],1)
        self.draft();self.say('Отмена');self.say('Сохранить учебное обращение')
        self.assertEqual(self.shared.execute('SELECT count(*) FROM incidents').fetchone()[0],1)
    def test_stale_dispatcher_note_requires_reopen(self):
        self.draft();self.say('Сохранить учебное обращение')
        self.say('/incident_status 1 review',22)
        with self.shared:miniapp.mutate(self.shared,'max:1','/api/incidents/comment',{'id':1,'version':1,'note':'Добавлено новое уточнение'})
        self.assertIn('уже изменено',self.say('Учебный разбор начат',22))
        self.assertEqual(incidents.detail(miniapp,self.shared,'max:1',1)['status'],'saved')
    def test_disabled_feature_fails_closed(self):
        with patch.dict('os.environ',{'TRAINING_INCIDENTS_ENABLED':'0'}):
            self.assertIn('не включены',self.say('/incidents'))
            self.assertIn('не включены',self.say('/incident_new'))
