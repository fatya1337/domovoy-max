"""Тестовый бот ЖКХ для MAX. Нет интеграций с 112, Госуслугами или реальной УК."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
EMERGENCY = (
    'Экстренная помощь — 112. При угрозе жизни или непосредственной опасности '
    'позвоните 112 с телефона, не ждите ответа бота.\n'
    'Бот не вызывает службы и не передаёт им сообщения или координаты. '
    'На компьютере воспользуйтесь телефоном.'
)
WELCOME = (
    'Домовой · тестовый прототип команды\n\n'
    'Помогу оформить учебную заявку по дому и проверить её статус. '
    'Заявки сохраняются только в нашей системе: реальная УК, 112 и Госуслуги не подключены. '
    'Для проверки используйте вымышленные адреса и описания.\n\n'
    'Новая заявка → адрес → описание → подтверждение.\n'
    'Для экстренной помощи: 112. /help — команды.'
)
MENU = ['Новая заявка', 'Мои заявки', 'Экстренная помощь', 'Помощь']
CANCEL = ['Отмена', 'Экстренная помощь']
STATUS = {'new': 'Зарегистрирована в прототипе', 'work': 'В работе (демо)',
          'done': 'Выполнена (демо)', 'confirmed': 'Результат подтверждён жителем',
          'reopened': 'Нужна повторная проверка (демо)'}


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


def connect(path):
    if str(path) != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript('''
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS drafts(user_id INTEGER PRIMARY KEY, stage TEXT, address TEXT, description TEXT);
      CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, address TEXT NOT NULL,
        description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
      CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY);
      CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, user_id INTEGER, body TEXT, sent INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    ''')
    return db


def reply(db, uid, text, buttons=MENU):
    body = {'text': text[:3900]}
    if buttons:
        body['attachments'] = [{'type': 'inline_keyboard', 'payload': {
            'buttons': [[{'type': 'message', 'text': label}] for label in buttons]}}]
    db.execute('INSERT INTO outbox(user_id,body) VALUES(?,?)', (uid, json.dumps(body, ensure_ascii=False)))


def ticket_text(row):
    return f"№{row['id']} · {STATUS[row['status']]}\n{row['address']}\n{row['description']}"


def handle(db, uid, text, admins, event_key=None):
    text = text.strip()
    command = text.casefold()
    if command in ('/112', '112', 'экстренная помощь'):
        reply(db, uid, EMERGENCY)
        return
    # Только дополнительная подсказка, не медицинская/аварийная классификация.
    # Кнопка 112 доступна независимо от совпадения слов; отсутствие совпадения не означает безопасность.
    if any(s in command for s in ('пожар', 'запах газа', 'пахнет газом', 'задыха', 'без сознания', 'взрыв')):
        reply(db, uid, EMERGENCY + '\n\nТекст не зарегистрирован как заявка. Для выхода из черновика — Отмена.')
        return
    if command == '/archive':
        rows = db.execute('SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 6', (uid,)).fetchall()
        reply(db, uid, 'Архив прежнего демобота. Эти записи не перенесены в базу домов.\n\n' + ('\n\n'.join(ticket_text(r) for r in rows) or 'Архив пуст.'), ['Меню', 'Мои заявки'])
        return
    if os.environ.get('APP_MODE') == 'max' and command not in ('/112', '112', 'экстренная помощь', '/id'):
        from connected_bot import respond_connected
        respond_connected(db, uid, text, event_key)
        return
    if command in ('/start', '/cancel', 'отмена'):
        db.execute('DELETE FROM drafts WHERE user_id=?', (uid,))
        reply(db, uid, WELCOME if command == '/start' else 'Черновик отменён.')
        return
    if command in ('/help', 'помощь'):
        reply(db, uid, 'Новая заявка — создать тестовое обращение.\nМои заявки — последние 10 обращений.\n'
              '/ticket НОМЕР — открыть свою заявку.\n/confirm НОМЕР — подтвердить выполненную работу.\n'
              '/reopen НОМЕР — сообщить, что проблема осталась.\nОтмена — удалить черновик.\n'
              '/id — ваш ID для настройки роли сотрудника.\n'
              'Сотруднику: /queue и /status НОМЕР work|done.\n\n' + EMERGENCY)
        return
    if command == '/id':
        reply(db, uid, f'Ваш MAX user_id: {uid}. Роль сотрудника назначается владельцем проекта в ADMIN_IDS.')
        return
    if command == '/queue' or command.startswith('/status'):
        if uid not in admins:
            reply(db, uid, 'Эта команда доступна только настроенным сотрудникам УК.')
            return
        if command == '/queue':
            rows = db.execute("SELECT * FROM tickets WHERE status != 'confirmed' ORDER BY id DESC LIMIT 10").fetchall()
            reply(db, uid, '\n\n'.join(ticket_text(r) for r in rows) or 'Очередь пуста.')
            return
        match = re.fullmatch(r'/status\s+(\d+)\s+(work|done)', command)
        if not match:
            reply(db, uid, 'Формат: /status НОМЕР work или /status НОМЕР done')
            return
        tid, status = int(match[1]), match[2]
        row = db.execute('SELECT * FROM tickets WHERE id=?', (tid,)).fetchone()
        allowed = {'work': ('new', 'reopened'), 'done': ('work',)}
        if not row or row['status'] not in allowed[status]:
            reply(db, uid, 'Заявка не найдена или переход недоступен. Сначала new → work → done.')
            return
        db.execute('UPDATE tickets SET status=? WHERE id=?', (status, tid))
        reply(db, uid, f'Заявка №{tid}: {STATUS[status]}.')
        message = f'Ваша тестовая заявка №{tid}: {STATUS[status]}.'
        if status == 'done':
            message += f'\nПроверьте результат: /confirm {tid} или /reopen {tid}.'
        if row['user_id'] != uid:
            reply(db, row['user_id'], message)
        elif status == 'done':
            reply(db, uid, message)
        return
    match = re.fullmatch(r'/(ticket|confirm|reopen)\s+(\d+)', command)
    if match:
        action, tid = match[1], int(match[2])
        row = db.execute('SELECT * FROM tickets WHERE id=? AND user_id=?', (tid, uid)).fetchone()
        if not row:
            reply(db, uid, 'Среди ваших заявок такой нет.')
            return
        if action == 'ticket':
            reply(db, uid, ticket_text(row))
        elif row['status'] != 'done':
            reply(db, uid, 'Подтвердить или вернуть на проверку можно заявку со статусом «Выполнена».')
        else:
            status = 'confirmed' if action == 'confirm' else 'reopened'
            db.execute('UPDATE tickets SET status=? WHERE id=?', (status, tid))
            reply(db, uid, f'Заявка №{tid}: {STATUS[status]}.')
        return
    if command in ('/my', 'мои заявки'):
        rows = db.execute('SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 10', (uid,)).fetchall()
        reply(db, uid, '\n\n'.join(ticket_text(r) for r in rows) or 'У вас пока нет заявок.')
        return
    if command in ('/new', 'новая заявка'):
        db.execute("INSERT OR REPLACE INTO drafts VALUES(?, 'address', '', '')", (uid,))
        reply(db, uid, 'Укажите тестовый адрес: город, улица, дом. Не вводите персональные данные.', CANCEL)
        return
    draft = db.execute('SELECT * FROM drafts WHERE user_id=?', (uid,)).fetchone()
    if not draft:
        reply(db, uid, 'Начните с кнопки «Новая заявка». Для экстренной помощи — 112.')
    elif draft['stage'] == 'address':
        if not 5 <= len(text) <= 180 or text.startswith('/'):
            reply(db, uid, 'Введите адрес длиной от 5 до 180 символов.', CANCEL)
            return
        db.execute("UPDATE drafts SET address=?, stage='description' WHERE user_id=?", (text, uid))
        reply(db, uid, 'Опишите проблему и место: например, «Не горит лампа, подъезд 2, этаж 3». Пока принимается только текст.', CANCEL)
    elif draft['stage'] == 'description':
        if not 10 <= len(text) <= 500 or text.startswith('/'):
            reply(db, uid, 'Нужно текстовое описание от 10 до 500 символов.', CANCEL)
            return
        db.execute("UPDATE drafts SET description=?, stage='confirm' WHERE user_id=?", (text, uid))
        reply(db, uid, f"Проверьте тестовую заявку:\n{draft['address']}\n{text}\n\n"
              'После подтверждения она появится только в нашем прототипе, не в реальной УК или 112.', ['Подтвердить заявку', 'Отмена', 'Экстренная помощь'])
    elif command == 'подтвердить заявку':
        cur = db.execute('INSERT INTO tickets(user_id,address,description) VALUES(?,?,?)',
                         (uid, draft['address'], draft['description']))
        db.execute('DELETE FROM drafts WHERE user_id=?', (uid,))
        reply(db, uid, f'Тестовая заявка №{cur.lastrowid} зарегистрирована в прототипе. Посмотреть: /ticket {cur.lastrowid}.')
    else:
        reply(db, uid, 'Подтвердите черновик кнопкой или отмените его.', ['Подтвердить заявку', 'Отмена', 'Экстренная помощь'])


def process(db, event, admins):
    kind = event.get('update_type')
    if kind == 'bot_started':
        uid = event.get('user', {}).get('user_id')
        text = '/start'
    elif kind == 'message_created':
        msg = event.get('message', {})
        if msg.get('sender', {}).get('is_bot') or msg.get('recipient', {}).get('chat_type') != 'dialog':
            return
        uid = msg.get('sender', {}).get('user_id')
        text = msg.get('body', {}).get('text') or ''
    else:
        return
    if not isinstance(uid, int) or isinstance(uid, bool):
        return
    mid = event.get('message', {}).get('body', {}).get('mid')
    eid = f'message:{mid}' if mid and kind == 'message_created' else hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
    with db:
        if db.execute('SELECT 1 FROM events WHERE id=?', (eid,)).fetchone():
            return
        handle(db, uid, text, admins, eid)
        db.execute('INSERT INTO events VALUES(?)', (eid,))


class APIError(RuntimeError):
    def __init__(self, status, path):
        self.status = status
        super().__init__(f'MAX API HTTP {status} ({path})')


class MaxAPI:
    def __init__(self):
        self.token = os.environ.get('MAX_BOT_TOKEN', '')
        if not self.token:
            raise RuntimeError('Заполните MAX_BOT_TOKEN в .env')
        self.base = os.environ.get('MAX_API_BASE', 'https://platform-api2.max.ru')
        if self.base != 'https://platform-api2.max.ru':
            raise RuntimeError('Для этого прототипа разрешён только официальный MAX API endpoint.')
        self.context = ssl.create_default_context()
        cert = Path(os.environ.get('MAX_CA_FILE', str(ROOT / 'certs/russian_trusted_root_ca.pem')))
        if cert.exists():
            self.context.load_verify_locations(cafile=str(cert))

    def request(self, method, path, query=None, body=None):
        url = self.base + path + ('?' + urllib.parse.urlencode(query) if query else '')
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method,
                  headers={'Authorization': self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Не включаем тело ответа, запрос или токен в лог.
            raise APIError(exc.code, path) from None


def flush(db, api):
    for row in db.execute('SELECT * FROM outbox WHERE sent=0 ORDER BY id LIMIT 20').fetchall():
        try:
            api.request('POST', '/messages', {'user_id': row['user_id']}, json.loads(row['body']))
        except APIError as exc:
            if exc.status not in (400, 403, 404):
                raise
            with db:
                db.execute('UPDATE outbox SET sent=-1 WHERE id=?', (row['id'],))
            logging.warning('Сообщение не доставлено (HTTP %s); сохранено для разбора.', exc.status)
            continue
        with db:
            db.execute('UPDATE outbox SET sent=1 WHERE id=?', (row['id'],))
        time.sleep(0.6)


def poll(db, api, admins):
    if api.request('GET', '/subscriptions').get('subscriptions'):
        raise RuntimeError('У бота уже есть Webhook. Остановлено без изменения существующей подписки.')
    logging.info('Тестовый бот запущен. Long Polling; внешние службы не подключены.')
    while True:
        try:
            if os.environ.get('APP_MODE') == 'max':
                import worker
                worker.cycle(db, api, admins)
            else:
                flush(db, api)
            row = db.execute("SELECT value FROM meta WHERE key='marker'").fetchone()
            query = {'timeout': 25, 'limit': 20, 'types': 'bot_started,message_created'}
            if row:
                query['marker'] = int(row['value'])
            result = api.request('GET', '/updates', query)
            for event in result.get('updates', []):
                process(db, event, admins)
            if result.get('marker') is not None:
                with db:
                    db.execute("INSERT OR REPLACE INTO meta VALUES('marker', ?)", (str(result['marker']),))
        except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError):
            logging.warning('Не удалось обработать обновление или доставить ответ. Повтор через 5 секунд; данные сохранены.')
            time.sleep(5)


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['check', 'poll'])
    args = parser.parse_args()
    api = MaxAPI()
    if args.command == 'check':
        info = api.request('GET', '/me')
        print(json.dumps({k: info.get(k) for k in ('user_id', 'first_name', 'username', 'is_bot')}, ensure_ascii=False))
        return
    if os.environ.get('APP_MODE') == 'max':
        import miniapp
        miniapp.init()
    admins = {int(s.strip()) for s in os.environ.get('ADMIN_IDS', '').split(',') if s.strip()}
    db = connect(os.environ.get('DATABASE_PATH', str(ROOT / 'data/bot.sqlite3')))
    try:
        poll(db, api, admins)
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    main()
