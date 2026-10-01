"""Local demo or signed MAX pilot, with separate databases and server-assigned roles."""
import json
import sys
import incidents
import os
import hmac
import hashlib
from contextlib import closing
from max_auth import validate_init_data
from pathlib import Path
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('MINIAPP_DATABASE_PATH', str(ROOT / 'data/miniapp.sqlite3')))
MODE = os.environ.get('APP_MODE', 'demo')
PUBLIC_ORIGIN = os.environ.get('PUBLIC_ORIGIN', '').rstrip('/')
PROFILES = {'anna': {'id': 'anna', 'name': 'Анна', 'role': 'resident', 'label': 'Анна · житель'},
            'boris': {'id': 'boris', 'name': 'Борис', 'role': 'resident', 'label': 'Борис · житель'},
            'dispatcher': {'id':'dispatcher','name':'Илья','role':'dispatcher','label':'Илья · учебный диспетчер'},
            'manager': {'id': 'manager', 'name': 'Мария', 'role': 'manager', 'label': 'Мария · УК'}}


def is_manager(profile):
    if MODE == 'demo' and profile == 'manager':
        return True
    return profile in {'max:' + s.strip() for s in os.environ.get('ADMIN_IDS', '').split(',') if s.strip()}


def person(db, profile):
    if MODE == 'demo' and profile in PROFILES:
        return PROFILES[profile]
    row = db.execute('SELECT name FROM users WHERE id=?', (profile,)).fetchone()
    name = row['name'] if row else 'Житель'
    role = 'manager' if is_manager(profile) else 'resident'
    return {'id': profile, 'name': name, 'role': role, 'label': name + (' · УК' if role == 'manager' else ' · житель')}


class Denied(Exception):
    pass


def connection(path=DB):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def init(path=DB):
    with closing(connection(path)) as db, db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS outages(id INTEGER PRIMARY KEY, title TEXT NOT NULL, service TEXT NOT NULL, reason TEXT NOT NULL, forecast TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'reported', version INTEGER NOT NULL DEFAULT 1, author TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP, updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS outage_houses(outage_id INTEGER REFERENCES outages(id), house_id INTEGER REFERENCES houses(id), PRIMARY KEY(outage_id,house_id));
        CREATE TABLE IF NOT EXISTS outage_events(id INTEGER PRIMARY KEY, outage_id INTEGER REFERENCES outages(id), author TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL, forecast TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS bot_sessions(profile TEXT PRIMARY KEY, stage TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS connected_replies(event_id TEXT PRIMARY KEY, profile TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bot_events(id TEXT PRIMARY KEY, body TEXT NOT NULL, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS app_outbox(id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, sent INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS houses(id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entrances(id INTEGER PRIMARY KEY, house_id INTEGER REFERENCES houses(id), number INTEGER, code TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS members(profile TEXT, entrance_id INTEGER REFERENCES entrances(id), UNIQUE(profile,entrance_id));
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, entrance_id INTEGER REFERENCES entrances(id), author TEXT, text TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY, entrance_id INTEGER REFERENCES entrances(id), title TEXT, text TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, entrance_id INTEGER REFERENCES entrances(id), author TEXT, title TEXT, status TEXT DEFAULT 'new', created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS notice_reads(notice_id INTEGER NOT NULL REFERENCES notices(id), profile TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(notice_id,profile));
        CREATE TABLE IF NOT EXISTS mutation_receipts(profile TEXT NOT NULL, request_id TEXT NOT NULL, digest TEXT NOT NULL, result TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(profile,request_id));
        CREATE TABLE IF NOT EXISTS ticket_events(id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id), author TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', status TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS ticket_events_ticket ON ticket_events(ticket_id,id);
        CREATE INDEX IF NOT EXISTS tickets_entrance ON tickets(entrance_id,id);
        CREATE INDEX IF NOT EXISTS messages_entrance ON messages(entrance_id,id);
        ''')
        incidents.init(db)
        # Serialize migrations and demo seeding across app/poller startup.
        db.execute('BEGIN IMMEDIATE')
        columns = {r['name'] for r in db.execute('PRAGMA table_info(tickets)')}
        for name, definition in [('category', "TEXT NOT NULL DEFAULT 'other'"), ('details', "TEXT NOT NULL DEFAULT ''"), ('outage_id', 'INTEGER REFERENCES outages(id)')]:
            if name not in columns:
                db.execute(f'ALTER TABLE tickets ADD COLUMN {name} {definition}')
        if MODE != 'demo' or db.execute('SELECT count(*) FROM houses').fetchone()[0]:
            return
        db.execute("INSERT INTO houses VALUES(1,'Соседи у парка','Тестоград, Парковая улица, 12')")
        for i in range(1, 4):
            db.execute('INSERT INTO entrances VALUES(?,?,?,?)', (i, 1, i, f'PARK-0{i}'))
        db.executemany('INSERT INTO members VALUES(?,?)', [('anna', 1), ('boris', 2)])
        db.execute("INSERT INTO notices(entrance_id,title,text) VALUES(1,'Проверка освещения','В четверг мастер проверит светильники на всех этажах. Если заметили неисправность — оставьте заявку.')")
        db.execute("INSERT INTO notices(entrance_id,title,text) VALUES(2,'Уборка подъезда','В пятницу запланирована влажная уборка лестничных площадок.')")
        db.execute("INSERT INTO messages(entrance_id,author,text) VALUES(1,'manager','Добро пожаловать! Здесь обсуждаем вопросы первого подъезда. Заявки на работы оставляйте в отдельном разделе.')")
        db.execute("INSERT INTO messages(entrance_id,author,text) VALUES(2,'boris','Привет, соседи второго подъезда!')")
        db.execute("INSERT INTO tickets(entrance_id,author,title,status) VALUES(1,'anna','Лампа на третьем этаже не горит','work')")


def access(db, profile, eid):
    row = db.execute('SELECT * FROM entrances WHERE id=?', (eid,)).fetchone()
    if not row:
        raise ValueError('Подъезд не найден')
    if not is_manager(profile) and not db.execute('SELECT 1 FROM members WHERE profile=? AND entrance_id=?', (profile, eid)).fetchone():
        raise Denied('Этот подъезд вам недоступен. Вступите по приглашению УК.')
    return row


def state(db, profile, eid=None):
    if is_manager(profile):
        entrances = db.execute('SELECT e.*,h.name,h.address FROM entrances e JOIN houses h ON h.id=e.house_id ORDER BY h.id,e.number').fetchall()
    else:
        entrances = db.execute('SELECT e.id,e.house_id,e.number,h.name,h.address FROM entrances e JOIN houses h ON h.id=e.house_id JOIN members m ON m.entrance_id=e.id WHERE m.profile=? ORDER BY h.id,e.number', (profile,)).fetchall()
    if eid is None and entrances:
        eid = entrances[0]['id']
    result = {'profile': person(db, profile), 'profiles': [], 'entrances': [dict(r) for r in entrances],
              'training_incidents': incidents.enabled(sys.modules[__name__]), 'dispatcher': incidents.dispatcher(sys.modules[__name__],profile), 'selected': eid, 'outages': [], 'messages': [], 'notices': [], 'tickets': [], 'members': [], 'demo': MODE == 'demo', 'stats': {'open': 0, 'done': 0, 'confirmed': 0, 'total': 0}}
    if eid is not None:
        access(db, profile, eid)
        result['outages'] = house_outages(db, profile, eid)
        result['messages'] = [dict(r) for r in db.execute('SELECT * FROM (SELECT * FROM messages WHERE entrance_id=? ORDER BY id DESC LIMIT 100) ORDER BY id', (eid,))]
        result['notices'] = [dict(r) for r in db.execute('''SELECT n.*,
            EXISTS(SELECT 1 FROM notice_reads nr WHERE nr.notice_id=n.id AND nr.profile=?) acknowledged,
            (SELECT count(*) FROM notice_reads nr JOIN members m ON m.profile=nr.profile AND m.entrance_id=n.entrance_id WHERE nr.notice_id=n.id) read_count
            FROM notices n WHERE entrance_id=? ORDER BY id DESC LIMIT 30''', (profile, eid))]
        result['tickets'] = [dict(r) for r in db.execute('SELECT * FROM tickets WHERE entrance_id=? ORDER BY id DESC LIMIT 50', (eid,))]
        counts = {r['status']: r['n'] for r in db.execute('SELECT status,count(*) n FROM tickets WHERE entrance_id=? GROUP BY status', (eid,))}
        result['stats'] = {'open': counts.get('new', 0)+counts.get('work', 0), 'done': counts.get('done', 0), 'confirmed': counts.get('confirmed', 0), 'total': sum(counts.values())}
        result['members'] = [person(db, r['profile']) for r in db.execute('SELECT profile FROM members WHERE entrance_id=?', (eid,))]
    ids = {profile} | {r['author'] for r in result['messages']} | {r['author'] for r in result['tickets']} | {r['id'] for r in result['members']}
    result['profiles'] = [person(db, uid) for uid in sorted(ids)]
    return result


CATEGORIES = {'light', 'water', 'clean', 'lift', 'door', 'other'}


def ticket_detail(db, profile, ticket_id):
    row = db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone()
    if not row:
        raise ValueError('Заявка не найдена')
    access(db, profile, row['entrance_id'])
    events = [dict(r) for r in db.execute('SELECT * FROM ticket_events WHERE ticket_id=? ORDER BY id', (ticket_id,))]
    ids = {row['author'], profile} | {e['author'] for e in events}
    return {'ticket': dict(row), 'outage': linked_outage(db,row['entrance_id'],row['outage_id']), 'events': events, 'profiles': [person(db, uid) for uid in sorted(ids)]}


def manager_queue(db, profile):
    if not is_manager(profile):
        raise Denied('Общая очередь доступна только УК')
    counts = {r['status']: r['n'] for r in db.execute('SELECT status,count(*) n FROM tickets GROUP BY status')}
    tickets = [dict(r) for r in db.execute("""SELECT t.*,e.number,h.address,h.name,h.id house_id FROM tickets t
              JOIN entrances e ON e.id=t.entrance_id JOIN houses h ON h.id=e.house_id
              WHERE t.status!='confirmed' ORDER BY CASE t.status WHEN 'new' THEN 0 WHEN 'work' THEN 1 ELSE 2 END,t.id LIMIT 100""")]
    return {'tickets': tickets, 'counts': counts, 'profiles': [person(db, uid) for uid in sorted({t['author'] for t in tickets})]}


def optional_field(body, key, high):
    value = body.get(key, '')
    if not isinstance(value, str) or len(value.strip()) > high:
        raise ValueError(f'Поле {key}: не больше {high} символов')
    return value.strip()


def field(body, key, low=1, high=1000):
    v = body.get(key)
    if not isinstance(v, str) or not low <= len(v.strip()) <= high:
        raise ValueError(f'Поле {key}: от {low} до {high} символов')
    return v.strip()


def apply_mutation(db, profile, route, body):
    request_id = body.get('request_id')
    if request_id is None:
        return mutate(db, profile, route, body)
    if not isinstance(request_id, str) or not 16 <= len(request_id) <= 80 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in request_id):
        raise ValueError('Неверный идентификатор запроса')
    digest = hashlib.sha256(json.dumps([route, body], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    db.execute('BEGIN IMMEDIATE')
    saved = db.execute('SELECT digest,result FROM mutation_receipts WHERE profile=? AND request_id=?', (profile, request_id)).fetchone()
    if saved:
        if not hmac.compare_digest(saved['digest'], digest):
            raise ValueError('Этот запрос уже использован для другого действия')
        return json.loads(saved['result'])
    result = mutate(db, profile, route, body)
    db.execute('INSERT INTO mutation_receipts(profile,request_id,digest,result) VALUES(?,?,?,?)',
               (profile, request_id, digest, json.dumps(result, ensure_ascii=False)))
    return result


OUTAGE_STATUSES = {'reported': 'Сообщение опубликовано', 'work': 'Идут работы', 'restored': 'Восстановлено'}
OUTAGE_SERVICES = {'water', 'power', 'heating', 'other'}


def house_outages(db, profile, eid):
    entrance = access(db, profile, eid)
    rows = db.execute("""SELECT o.* FROM outages o JOIN outage_houses oh ON oh.outage_id=o.id
                         WHERE oh.house_id=? ORDER BY CASE WHEN o.status='restored' THEN 1 ELSE 0 END,o.id DESC LIMIT 30""", (entrance['house_id'],)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['source'] = 'Демонстрационная УК' if MODE == 'demo' else 'УК в Домовом'
        item['history'] = [dict(r) for r in db.execute('SELECT status,note,forecast,created FROM outage_events WHERE outage_id=? ORDER BY id DESC LIMIT 10', (row['id'],))]
        # Residents see their selected house only, not addresses of other participants.
        item['houses'] = [dict(r) for r in db.execute('SELECT h.id,h.address FROM houses h JOIN outage_houses oh ON oh.house_id=h.id WHERE oh.outage_id=? AND (? OR h.id=?)', (row['id'], is_manager(profile), entrance['house_id']))]
        item.pop('author')
        result.append(item)
    return result


def linked_outage(db,eid,oid):
    if oid is None:return None
    row=db.execute("""SELECT o.id,o.title,o.reason,o.forecast,o.status,o.updated FROM outages o JOIN outage_houses oh ON oh.outage_id=o.id JOIN entrances e ON e.house_id=oh.house_id WHERE e.id=? AND o.id=?""",(eid,oid)).fetchone()
    if not row:return None
    return {**dict(row),'source':'Демонстрационная УК' if MODE=='demo' else 'УК в Домовом'}


def validate_ticket_outage(db,eid,oid):
    if oid is None:return None
    if type(oid) is not int or oid<=0:raise ValueError('Выберите аварию из списка своего дома')
    item=linked_outage(db,eid,oid)
    if not item or item['status']=='restored':raise ValueError('Авария недоступна или уже завершена. Обновите список.')
    return item


def notify_outage(db, oid):
    if MODE != 'max':
        return
    row = db.execute('SELECT * FROM outages WHERE id=?', (oid,)).fetchone()
    text = f'Обновление от УК в Домовом · авария №{oid}\n{row["title"]}\n{OUTAGE_STATUSES[row["status"]]}\nПричина: {row["reason"]}'
    latest = db.execute('SELECT note FROM outage_events WHERE outage_id=? ORDER BY id DESC LIMIT 1', (oid,)).fetchone()
    if latest and latest['note'] != row['reason']:
        text += '\nОбновление: ' + latest['note']
    text += '\nОбновлено: ' + row['updated'] + ' UTC'
    if row['status'] != 'restored':
        text += '\nПрогноз (не гарантия): ' + (row['forecast'] or 'Срок уточняется')
    text += '\nПроверить сведения: Аварии дома'
    users = db.execute("""SELECT DISTINCT m.profile FROM members m JOIN entrances e ON e.id=m.entrance_id
                         JOIN outage_houses oh ON oh.house_id=e.house_id WHERE oh.outage_id=?""", (oid,))
    for user in users:
        uid = user['profile']
        if uid.startswith('max:') and uid[4:].isdecimal():
            db.execute('INSERT INTO app_outbox(user_id,text) VALUES(?,?)', (int(uid[4:]), text))


def mutate_outage(db, profile, route, body):
    if not is_manager(profile):
        raise Denied('Публиковать и обновлять аварии может только УК')
    if route == '/api/outages':
        houses = body.get('house_ids')
        if not isinstance(houses, list) or not 1 <= len(houses) <= 20 or any(type(h) is not int or h <= 0 for h in houses):
            raise ValueError('Выберите от 1 до 20 домов')
        houses = list(dict.fromkeys(houses))
        for hid in houses:
            if not db.execute('SELECT 1 FROM houses WHERE id=?', (hid,)).fetchone():
                raise ValueError('Дом не найден')
        service = body.get('service')
        if not isinstance(service, str) or service not in OUTAGE_SERVICES:
            raise ValueError('Выберите коммунальную услугу')
        title = field(body, 'title', 5, 120)
        reason = field(body, 'reason', 5, 1000)
        forecast = optional_field(body, 'forecast', 120)
        oid = db.execute('INSERT INTO outages(title,service,reason,forecast,author) VALUES(?,?,?,?,?)', (title, service, reason, forecast, profile)).lastrowid
        db.executemany('INSERT INTO outage_houses VALUES(?,?)', [(oid,hid) for hid in houses])
        db.execute("INSERT INTO outage_events(outage_id,author,status,note,forecast) VALUES(?,?,'reported',?,?)", (oid,profile,reason,forecast))
    else:
        oid = int(body.get('id', 0))
        row = db.execute('SELECT * FROM outages WHERE id=?', (oid,)).fetchone()
        if not row:
            raise ValueError('Авария не найдена')
        status = body.get('status')
        allowed = {'reported': ['reported','work','restored'], 'work': ['work','restored'], 'restored': []}
        if status not in allowed[row['status']]:
            raise ValueError('Этот переход недоступен. Для нового отключения создайте новую карточку.')
        note = field(body, 'note', 5, 1000)
        forecast = optional_field(body, 'forecast', 120) if status != 'restored' else ''
        if type(body.get('version')) is not int:
            raise ValueError('Обновите карточку перед изменением')
        changed = db.execute('UPDATE outages SET status=?,forecast=?,version=version+1,updated=CURRENT_TIMESTAMP WHERE id=? AND version=?', (status,forecast,oid,body['version'])).rowcount
        if not changed:
            raise ValueError('Карточку уже изменили. Обновите страницу и повторите действие.')
        db.execute('INSERT INTO outage_events(outage_id,author,status,note,forecast) VALUES(?,?,?,?,?)', (oid,profile,status,note,forecast))
    notify_outage(db, oid)
    return {'ok': True, 'outage_id': oid}


def mutate(db, profile, route, body):
    if route in ('/api/incidents','/api/incidents/update','/api/incidents/comment'):
        return incidents.mutate(sys.modules[__name__],db,profile,route,body)
    if route in ('/api/outages', '/api/outages/update'):
        return mutate_outage(db, profile, route, body)
    if route == '/api/houses':
        if not is_manager(profile):
            raise Denied('Создавать дома может только УК')
        name, address = field(body, 'name', 2, 80), field(body, 'address', 5, 160)
        count = int(body.get('count', 0))
        if not 1 <= count <= 20:
            raise ValueError('Выберите от 1 до 20 подъездов')
        hid = db.execute('INSERT INTO houses(name,address) VALUES(?,?)', (name, address)).lastrowid
        first = None
        for number in range(1, count+1):
            eid = db.execute('INSERT INTO entrances(house_id,number,code) VALUES(?,?,?)',
                             (hid, number, secrets.token_hex(8).upper())).lastrowid
            first = first or eid
        return {'entrance_id': first}
    if route == '/api/join':
        if is_manager(profile):
            raise ValueError('УК уже видит все подъезды')
        code = field(body, 'code', 3, 40).upper()
        row = db.execute('SELECT id FROM entrances WHERE code=?', (code,)).fetchone()
        if not row:
            raise ValueError('Код не найден. Проверьте приглашение.')
        db.execute('INSERT OR IGNORE INTO members VALUES(?,?)', (profile, row['id']))
        return {'entrance_id': row['id']}
    eid = int(body.get('entrance_id', 0))
    access(db, profile, eid)
    if route == '/api/invite/rotate':
        if not is_manager(profile):
            raise Denied('Менять приглашения может только УК')
        code = secrets.token_hex(8).upper()
        db.execute('UPDATE entrances SET code=? WHERE id=?', (code, eid))
        return {'code': code, 'entrance_id': eid}
    if route == '/api/messages':
        db.execute('INSERT INTO messages(entrance_id,author,text) VALUES(?,?,?)', (eid, profile, field(body, 'text')))
    elif route == '/api/ticket/outage':
        row=db.execute('SELECT * FROM tickets WHERE id=? AND entrance_id=?',(int(body.get('id',0)),eid)).fetchone()
        if not row:raise ValueError('Заявка не найдена')
        if not is_manager(profile) and row['author']!=profile:raise Denied('Связь меняют автор заявки или УК')
        if row['status']=='confirmed':raise ValueError('Результат заявки уже подтверждён')
        if 'outage_id' not in body:raise ValueError('Укажите аварию или null для снятия связи')
        if (body['outage_id'] is None or type(body['outage_id']) is int) and row['outage_id']==body['outage_id']:
            return {'ok':True}
        outage=validate_ticket_outage(db,eid,body['outage_id'])
        if row['outage_id']!=body['outage_id']:
            db.execute('UPDATE tickets SET outage_id=? WHERE id=?',(body['outage_id'],row['id']))
            note=f'Связана с аварией №{outage["id"]}: {outage["title"]}' if outage else 'Связь с общей аварией снята'
            db.execute("INSERT INTO ticket_events(ticket_id,author,kind,text) VALUES(?,?,'outage',?)",(row['id'],profile,note))
        return {'ok':True}
    elif route == '/api/tickets':
        category = body.get('category', 'other')
        if not isinstance(category, str) or category not in CATEGORIES:
            raise ValueError('Выберите категорию заявки')
        outage=validate_ticket_outage(db,eid,body.get('outage_id'))
        tid = db.execute('INSERT INTO tickets(entrance_id,author,title,category,details,outage_id) VALUES(?,?,?,?,?,?)',
                         (eid, profile, field(body, 'title', 5, 300), category, optional_field(body, 'details', 2000),body.get('outage_id'))).lastrowid
        db.execute("INSERT INTO ticket_events(ticket_id,author,kind,status) VALUES(?,?,'created','new')", (tid, profile))
        if outage:
            db.execute("INSERT INTO ticket_events(ticket_id,author,kind,text) VALUES(?,?,'outage',?)",(tid,profile,f'Связана с аварией №{outage["id"]}: {outage["title"]}'))
        return {'ok': True, 'ticket_id': tid}
    elif route == '/api/ticket/comment':
        row = db.execute('SELECT id FROM tickets WHERE id=? AND entrance_id=?', (int(body.get('id', 0)), eid)).fetchone()
        if not row:
            raise ValueError('Заявка не найдена')
        db.execute("INSERT INTO ticket_events(ticket_id,author,kind,text) VALUES(?,?,'comment',?)", (row['id'], profile, field(body, 'text', 1, 1500)))
    elif route == '/api/notices':
        if not is_manager(profile):
            raise Denied('Публиковать объявления может только УК')
        title, text = field(body, 'title', 3, 100), field(body, 'text', 5, 1500)
        scope = body.get('scope', 'entrance')
        if scope not in ('entrance', 'house'):
            raise ValueError('Выберите получателей объявления')
        target_ids = [eid]
        if scope == 'house':
            hid = db.execute('SELECT house_id FROM entrances WHERE id=?', (eid,)).fetchone()[0]
            target_ids = [r['id'] for r in db.execute('SELECT id FROM entrances WHERE house_id=?', (hid,))]
        db.executemany('INSERT INTO notices(entrance_id,title,text) VALUES(?,?,?)', [(target, title, text) for target in target_ids])
        return {'ok': True, 'entrances': len(target_ids)}
    elif route == '/api/notice/read':
        if is_manager(profile):
            raise Denied('Отметку ставят жители подъезда')
        notice = db.execute('SELECT id FROM notices WHERE id=? AND entrance_id=?', (int(body.get('id', 0)), eid)).fetchone()
        if not notice:
            raise ValueError('Объявление не найдено')
        db.execute('INSERT OR IGNORE INTO notice_reads(notice_id,profile) VALUES(?,?)', (notice['id'], profile))
    elif route == '/api/status':
        row = db.execute('SELECT * FROM tickets WHERE id=? AND entrance_id=?', (int(body.get('id', 0)), eid)).fetchone()
        if not row:
            raise ValueError('Заявка не найдена')
        status = body.get('status')
        allowed = {'new': ['work'], 'work': ['done'], 'done': ['confirmed', 'work'], 'confirmed': []}
        if status not in allowed[row['status']]:
            raise ValueError('Этот переход статуса недоступен')
        if is_manager(profile):
            if status == 'confirmed':
                raise Denied('Результат подтверждает автор заявки')
        elif row['author'] != profile or row['status'] != 'done' or status not in ('confirmed', 'work'):
            raise Denied('Вы можете подтвердить или вернуть только свою выполненную заявку')
        note = optional_field(body, 'note', 1500)
        changed = db.execute('UPDATE tickets SET status=? WHERE id=? AND status=?', (status, row['id'], row['status'])).rowcount
        if not changed:
            raise ValueError('Заявка уже изменена. Обновите страницу.')
        db.execute("INSERT INTO ticket_events(ticket_id,author,kind,text,status) VALUES(?,?,'status',?,?)", (row['id'], profile, note, status))
        if MODE == 'max' and row['author'].startswith('max:'):
            labels = {'work': 'В работе', 'done': 'Выполнена — подтвердите результат в приложении', 'confirmed': 'Результат подтверждён'}
            db.execute('INSERT INTO app_outbox(user_id,text) VALUES(?,?)', (int(row['author'][4:]), f'Заявка №{row["id"]}: {labels[status]}.'))
    else:
        raise ValueError('Неизвестное действие')
    return {'ok': True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, value, mime='application/json; charset=utf-8'):
        data = json.dumps(value, ensure_ascii=False).encode() if mime.startswith('application/json') else value
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        ancestors = "'none'" if MODE == 'demo' else "https://web.max.ru https://max.ru"
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' https://st.max.ru; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors " + ancestors)
        self.end_headers()
        self.wfile.write(data)

    def safe_host(self):
        allowed = ('127.0.0.1:8765', 'localhost:8765') if MODE == 'demo' else (urlparse(PUBLIC_ORIGIN).netloc,)
        return self.headers.get('Host') in allowed

    def profile(self):
        if MODE == 'max':
            try:
                user = validate_init_data(self.headers.get('X-Max-Init-Data'), os.environ.get('MAX_BOT_TOKEN', ''))
            except ValueError as exc:
                raise Denied(str(exc)) from None
            with closing(connection()) as db, db:
                db.execute('INSERT INTO users(id,name) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name', (user['id'], user['name']))
            return user['id']
        profile = self.headers.get('X-Demo-Profile', '')
        if profile not in PROFILES:
            raise Denied('Выберите демонстрационный профиль')
        return profile

    def do_GET(self):
        if not self.safe_host():
            return self.respond(403, {'error': 'Демонстрация доступна только локально'})
        url = urlparse(self.path)
        if url.path == '/api/config':
            return self.respond(200, {'mode': MODE})
        if url.path == '/health':
            return self.respond(200, {'ok': True})
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/request.js': ('request.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if url.path in files:
            name, mime = files[url.path]
            return self.respond(200, (ROOT/'web'/name).read_bytes(), mime)
        if url.path not in ('/api/state', '/api/ticket', '/api/queue', '/api/incidents'):
            return self.respond(404, {'error': 'Не найдено'})
        try:
            profile = self.profile()
            arg = parse_qs(url.query).get('entrance_id', [None])[0]
            with closing(connection()) as db, db:
                if url.path == '/api/incidents':
                    result = incidents.listing(sys.modules[__name__],db,profile)
                elif url.path == '/api/ticket':
                    result = ticket_detail(db, profile, int(parse_qs(url.query).get('id', ['0'])[0]))
                elif url.path == '/api/queue':
                    result = manager_queue(db, profile)
                else:
                    result = state(db, profile, int(arg) if arg is not None else None)
            self.respond(200, result)
        except Denied as e:
            self.respond(403, {'error': str(e)})
        except (ValueError, TypeError) as e:
            self.respond(400, {'error': str(e)})

    def do_POST(self):
        if self.path == '/webhook':
            if MODE != 'max' or not self.safe_host():
                return self.respond(404, {'error': 'Не найдено'})
            secret = os.environ.get('MAX_WEBHOOK_SECRET', '')
            if not secret or not hmac.compare_digest(self.headers.get('X-Max-Bot-Api-Secret', ''), secret):
                return self.respond(403, {'error': 'Forbidden'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 262144:
                    raise ValueError()
                event = json.loads(self.rfile.read(size))
                if not isinstance(event, dict) or not isinstance(event.get('update_type'), str):
                    raise ValueError()
                raw = json.dumps(event, sort_keys=True)
                key = hashlib.sha256(raw.encode()).hexdigest()
                with closing(connection()) as db, db:
                    db.execute('INSERT OR IGNORE INTO bot_events(id,body) VALUES(?,?)', (key, raw))
                return self.respond(200, {'ok': True})
            except (ValueError, TypeError):
                return self.respond(400, {'error': 'Invalid event'})
        origins = (None, 'http://127.0.0.1:8765', 'http://localhost:8765') if MODE == 'demo' else (PUBLIC_ORIGIN,)
        if not self.safe_host() or self.headers.get('Origin') not in origins:
            return self.respond(403, {'error': 'Действие недоступно'})
        try:
            profile = self.profile()
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length < 10000 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Неверный формат запроса')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Ожидается объект')
            with closing(connection()) as db, db:
                result = apply_mutation(db, profile, self.path, body)
            self.respond(200, result)
        except Denied as e:
            self.respond(403, {'error': str(e)})
        except (ValueError, TypeError) as e:
            self.respond(400, {'error': str(e)})


if __name__ == '__main__':
    if MODE not in ('demo', 'max'):
        raise SystemExit('APP_MODE must be demo or max')
    if MODE == 'max' and (not PUBLIC_ORIGIN.startswith('https://') or not os.environ.get('MAX_BOT_TOKEN')):
        raise SystemExit('MAX mode requires HTTPS PUBLIC_ORIGIN and MAX_BOT_TOKEN')
    if MODE == 'max' and not os.environ.get('MINIAPP_DATABASE_PATH'):
        raise SystemExit('Set MINIAPP_DATABASE_PATH explicitly to a separate non-demo database')
    init()
    if MODE == 'max':
        with closing(connection()) as db:
            if db.execute("SELECT 1 FROM members WHERE profile IN ('anna','boris','manager') LIMIT 1").fetchone():
                raise SystemExit('Demo database cannot be used in MAX mode')
    bind = '127.0.0.1' if MODE == 'demo' else '0.0.0.0'
    print(f'Miniapp mode={MODE}; port=8765', flush=True)
    ThreadingHTTPServer((bind, 8765), Handler).serve_forever()
