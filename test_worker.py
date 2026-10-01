import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bot
import miniapp
import worker


class WorkerTests(unittest.TestCase):
    def test_failed_recipient_does_not_block_next(self):
        db=bot.connect(':memory:')
        with db:
            bot.reply(db,1,'one');bot.reply(db,2,'two')
        class API:
            def request(self,method,path,query,body):
                if query['user_id']==1: raise bot.APIError(403,path)
                return {'message':{}}
        with patch.object(bot.time,'sleep'):
            bot.flush(db,API())
        self.assertEqual([r[0] for r in db.execute('SELECT sent FROM outbox ORDER BY id')],[-1,1])
        db.close()

    def test_notification_transfer_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(miniapp,'MODE','max'):
            path=Path(tmp)/'pilot.db';miniapp.init(path)
            shared=miniapp.connection(path)
            with shared: shared.execute("INSERT INTO app_outbox(user_id,text) VALUES(123,'Статус изменён')")
            original=miniapp.connection
            db=bot.connect(':memory:')
            with patch.object(miniapp,'connection',lambda:original(path)),patch.object(bot,'flush'):
                worker.cycle(db,None,set())
                # Simulate a crash before the shared DB transfer marker was committed.
                with shared: shared.execute('UPDATE app_outbox SET sent=0')
                worker.cycle(db,None,set())
            self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0],1)
            db.close();shared.close()


if __name__=='__main__': unittest.main()
