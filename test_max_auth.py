import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from max_auth import validate_init_data
import miniapp
import bot
import connected_bot

TOKEN = 'test-token-not-a-real-credential'
NOW = 1800000000


def signed(uid=123, timestamp=NOW, **extra):
    params = {'auth_date': str(timestamp), 'user': json.dumps({'id': uid, 'first_name': 'Тест & проверка = да'}, ensure_ascii=False), **extra}
    key = hmac.digest(b'WebAppData', TOKEN.encode(), 'sha256')
    value = '\n'.join(f'{k}={v}' for k,v in sorted(params.items()))
    return urlencode({**params, 'hash': hmac.digest(key, value.encode(), 'sha256').hex()})


class AuthTests(unittest.TestCase):
    def test_valid_unicode(self):
        user=validate_init_data(signed(),TOKEN,now=NOW)
        self.assertEqual(user['id'],'max:123')
        self.assertEqual(user['name'],'Тест & проверка = да')

    def test_tampering_and_wrong_bot(self):
        for raw,token in [(signed().replace('123','124'),TOKEN),(signed(),'wrong-token')]:
            with self.assertRaises(ValueError): validate_init_data(raw,token,now=NOW)

    def test_expiration_and_future(self):
        for stamp in (NOW-3601,NOW+31):
            with self.assertRaises(ValueError): validate_init_data(signed(timestamp=stamp),TOKEN,now=NOW)

    def test_duplicates_missing_and_malformed(self):
        for raw in (signed()+'&auth_date=1',signed()+'&hash=00','user=%GG','', 'hash='+'a'*64):
            with self.assertRaises(ValueError): validate_init_data(raw,TOKEN,now=NOW)

    def test_bool_id_rejected(self):
        with self.assertRaises(ValueError): validate_init_data(signed(uid=True),TOKEN,now=NOW)

    def test_server_role_only(self):
        with patch.object(miniapp,'MODE','max'),patch.dict('os.environ',{'ADMIN_IDS':'123'}):
            self.assertTrue(miniapp.is_manager('max:123'))
            self.assertFalse(miniapp.is_manager('max:456'))
            self.assertFalse(miniapp.is_manager('manager'))

    def test_live_database_has_no_demo_and_bot_reads_same_tickets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(miniapp,'MODE','max'),patch.dict('os.environ',{'ADMIN_IDS':'123','APP_MODE':'max'}):
            path=Path(tmp)/'pilot.sqlite3'
            miniapp.init(path)
            db=miniapp.connection(path)
            self.assertEqual(db.execute('SELECT count(*) FROM houses').fetchone()[0],0)
            with db:
                db.execute("INSERT INTO users VALUES('max:456','Житель')")
                eid=miniapp.mutate(db,'max:123','/api/houses',{'name':'Дом','address':'Тестовый адрес 1','count':1})['entrance_id']
                code=db.execute('SELECT code FROM entrances').fetchone()[0]
                miniapp.mutate(db,'max:456','/api/join',{'code':code})
                miniapp.mutate(db,'max:456','/api/tickets',{'entrance_id':eid,'title':'Проверка общей базы'})
                miniapp.mutate(db,'max:123','/api/status',{'entrance_id':eid,'id':1,'status':'work'})
            self.assertEqual(db.execute('SELECT user_id FROM app_outbox').fetchone()[0],456)
            db.close()
            local=bot.connect(':memory:')
            original=miniapp.connection
            with patch.object(miniapp,'connection',lambda: original(path)):
                connected_bot.respond_connected(local,456,'Мои заявки')
                connected_bot.respond_connected(local,789,'Мои заявки')
            texts=[json.loads(r[0])['text'] for r in local.execute('SELECT body FROM outbox ORDER BY id')]
            self.assertIn('Проверка общей базы',texts[0])
            self.assertNotIn('Проверка общей базы',texts[1])
            local.close()


if __name__=='__main__': unittest.main()
