import json
import unittest
from bot import connect, handle, process


class BotTest(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')

    def tearDown(self):
        self.db.close()

    def say(self, text, uid=1):
        with self.db:
            handle(self.db, uid, text, {99})

    def create(self, uid=1):
        for text in ('Новая заявка', 'Тестоград, Примерная, 1', 'Не горит лампа на втором этаже', 'Подтвердить заявку'):
            self.say(text, uid)

    def last(self):
        return json.loads(self.db.execute('SELECT body FROM outbox ORDER BY id DESC LIMIT 1').fetchone()[0])['text']

    def test_confirm_required_and_no_double_submission(self):
        for t in ('Новая заявка', 'Тестоград, Примерная, 1', 'Не горит лампа на втором этаже'):
            self.say(t)
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0], 0)
        self.say('Подтвердить заявку')
        self.say('Подтвердить заявку')
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0], 1)

    def test_complete_lifecycle(self):
        self.create()
        self.say('/status 1 work', 99)
        self.say('/status 1 done', 99)
        self.say('/reopen 1')
        self.say('/status 1 work', 99)
        self.say('/status 1 done', 99)
        self.say('/confirm 1')
        self.assertEqual(self.db.execute('SELECT status FROM tickets').fetchone()[0], 'confirmed')

    def test_access_control(self):
        self.create()
        self.say('/ticket 1', 2)
        self.assertIn('такой нет', self.last())
        self.say('/status 1 work', 2)
        self.assertIn('только настроенным', self.last())
        self.say('/confirm 1', 2)
        self.assertEqual(self.db.execute('SELECT status FROM tickets').fetchone()[0], 'new')
        self.say('/my', 2)
        self.assertNotIn('Примерная', self.last())

    def test_invalid_transition(self):
        self.create()
        self.say('/status 1 done', 99)
        self.say('/confirm 1')
        self.assertEqual(self.db.execute('SELECT status FROM tickets').fetchone()[0], 'new')

    def test_emergency_does_not_create_ticket(self):
        self.say('Новая заявка')
        self.say('Тестоград, Примерная, 1')
        self.say('В подъезде пахнет газом')
        self.assertIn('не вызывает службы', self.last())
        self.assertEqual(self.db.execute('SELECT count(*) FROM tickets').fetchone()[0], 0)

    def test_replayed_event(self):
        event = {'update_type': 'message_created', 'message': {'sender': {'user_id': 1},
                 'recipient': {'chat_type': 'dialog'}, 'body': {'mid': 'abc', 'text': 'Новая заявка'}}}
        process(self.db, event, set())
        self.say('Тестоград, Примерная, 1')
        process(self.db, event, set())
        self.assertEqual(self.db.execute('SELECT stage FROM drafts').fetchone()[0], 'description')

    def test_groups_and_bots_ignored(self):
        event = {'update_type': 'message_created', 'message': {'sender': {'user_id': 1},
                 'recipient': {'chat_type': 'chat'}, 'body': {'mid': 'abc', 'text': 'Новая заявка'}}}
        process(self.db, event, set())
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_cancel_and_invalid_input(self):
        self.say('Новая заявка')
        self.say('x')
        self.assertEqual(self.db.execute('SELECT stage FROM drafts').fetchone()[0], 'address')
        self.say('Отмена')
        self.assertIsNone(self.db.execute('SELECT * FROM drafts').fetchone())


if __name__ == '__main__':
    unittest.main()
