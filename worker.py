"""Webhook worker, separated from HTTP ingress. Events remain durable in SQLite."""
import json
import logging
import os
import time
from contextlib import closing
from urllib.error import URLError
import bot
import miniapp


def cycle(db, api, admins):
    with closing(miniapp.connection()) as shared:
        for event in shared.execute('SELECT id,body FROM bot_events WHERE done=0 LIMIT 20').fetchall():
            bot.process(db, json.loads(event['body']), admins)
            with shared:
                shared.execute('UPDATE bot_events SET done=1 WHERE id=?', (event['id'],))
        # A durable transfer into the bot outbox, with a per-notification dedup key.
        for item in shared.execute('SELECT * FROM app_outbox WHERE sent=0 LIMIT 20').fetchall():
            key = 'miniapp-notification:' + str(item['id'])
            with db:
                if not db.execute('SELECT 1 FROM events WHERE id=?', (key,)).fetchone():
                    buttons = ['Учебные обращения'] if 'учебное обращение' in item['text'] else ['Аварии дома'] if 'Аварии дома' in item['text'] else ['Мои заявки']
                    bot.reply(db, item['user_id'], item['text'], buttons)
                    db.execute('INSERT INTO events VALUES(?)', (key,))
            with shared:
                shared.execute('UPDATE app_outbox SET sent=1 WHERE id=?', (item['id'],))
    bot.flush(db, api)


if __name__ == '__main__':
    if os.environ.get('APP_MODE') != 'max':
        raise SystemExit('worker requires APP_MODE=max')
    miniapp.init()
    api = bot.MaxAPI()
    db = bot.connect(os.environ.get('DATABASE_PATH', '/app/data/bot.sqlite3'))
    admins = {int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip()}
    logging.basicConfig(level=logging.INFO)
    logging.info('Webhook worker started')
    while True:
        try:
            cycle(db, api, admins)
        except (RuntimeError, URLError, TimeoutError, ValueError):
            logging.warning('Delivery unavailable; persisted work will be retried')
            time.sleep(5)
        time.sleep(1)
