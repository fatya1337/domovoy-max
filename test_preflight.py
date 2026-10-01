import unittest
from preflight import check


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.values={'APP_DOMAIN':'domovoy.team.ru','PUBLIC_ORIGIN':'https://domovoy.team.ru',
                     'MAX_BOT_TOKEN':'synthetic-token','MAX_WEBHOOK_SECRET':'x'*40,
                     'ADMIN_IDS':'123,456','MINIAPP_ENABLED':'0'}

    def test_complete_settings(self):
        self.assertEqual(check(self.values),[])

    def test_missing_admin_and_secret(self):
        self.values['ADMIN_IDS']='';self.values['MAX_WEBHOOK_SECRET']='short'
        self.assertEqual(len(check(self.values)),2)

    def test_placeholder_domain(self):
        self.values['APP_DOMAIN']='app.example.ru';self.values['PUBLIC_ORIGIN']='https://app.example.ru'
        self.assertTrue(check(self.values))

    def test_training_requires_separate_dispatchers(self):
        self.values['TRAINING_INCIDENTS_ENABLED']='1'
        self.assertTrue(check(self.values))
        self.values['DISPATCHER_IDS']='789'
        self.assertEqual(check(self.values),[])

    def test_mismatched_origin(self):
        self.values['PUBLIC_ORIGIN']='https://other.team.ru/path'
        self.assertTrue(check(self.values))


if __name__=='__main__':unittest.main()
