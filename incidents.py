"""Private TRAINING incidents. No external dispatch or identity verification."""
import os

STATUSES = {'saved':'Сохранено в учебной системе','review':'Учебный диспетчер изучает','clarify':'Нужно уточнение','closed':'Учебный разбор завершён'}

def enabled(app):
    return app.MODE == 'demo' or os.environ.get('TRAINING_INCIDENTS_ENABLED') == '1'

def dispatcher(app, profile):
    return (app.MODE == 'demo' and profile == 'dispatcher') or (app.MODE == 'max' and profile in {'max:'+x.strip() for x in os.environ.get('DISPATCHER_IDS','').split(',') if x.strip()})

def init(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY, author TEXT NOT NULL, address TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'saved', version INTEGER NOT NULL DEFAULT 1, created TEXT DEFAULT CURRENT_TIMESTAMP, updated TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS incident_events(id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL REFERENCES incidents(id), author TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX IF NOT EXISTS incidents_author ON incidents(author,id);
    CREATE INDEX IF NOT EXISTS incident_events_parent ON incident_events(incident_id,id);
    ''')

def check(app):
    if not enabled(app): raise app.Denied('Учебные обращения здесь не включены')

def detail(app,db,profile,iid):
    check(app)
    row=db.execute('SELECT * FROM incidents WHERE id=?',(iid,)).fetchone()
    if not row or (row['author']!=profile and not dispatcher(app,profile)):
        raise app.Denied('Обращение недоступно')
    item=dict(row)
    item['events']=[{'status':e['status'],'note':e['note'],'created':e['created'],'actor':'Заявитель' if e['author']==row['author'] else 'Учебный диспетчер'} for e in db.execute('SELECT * FROM incident_events WHERE incident_id=? ORDER BY id',(iid,))]
    item.pop('author')
    return item

def listing(app,db,profile):
    check(app)
    if dispatcher(app,profile):
        rows=db.execute('SELECT id FROM incidents ORDER BY CASE WHEN status=\'closed\' THEN 1 ELSE 0 END,id DESC LIMIT 50')
    else:
        rows=db.execute('SELECT id FROM incidents WHERE author=? ORDER BY id DESC LIMIT 50',(profile,))
    items=[detail(app,db,profile,r['id']) for r in rows]
    where,args=('',()) if dispatcher(app,profile) else (' WHERE author=?',(profile,))
    counts={r['status']:r['n'] for r in db.execute('SELECT status,count(*) n FROM incidents'+where+' GROUP BY status',args)}
    return {'dispatcher':dispatcher(app,profile),'incidents':items,'counts':counts}

def mutate(app,db,profile,route,body):
    check(app)
    if route=='/api/incidents':
        if body.get('training_ack') is not True: raise ValueError('Подтвердите учебный характер обращения')
        address=app.field(body,'address',5,240)
        description=app.field(body,'description',10,2000)
        iid=db.execute('INSERT INTO incidents(author,address,description) VALUES(?,?,?)',(profile,address,description)).lastrowid
        db.execute('INSERT INTO incident_events(incident_id,author,status,note) VALUES(?,?,?,?)',(iid,profile,'saved','Учебное обращение сохранено. В 112 не передавалось.'))
        return {'ok':True,'incident_id':iid}
    item=detail(app,db,profile,int(body.get('id',0)))
    if type(body.get('version')) is not int or body['version']!=item['version']: raise ValueError('Обращение уже изменено. Обновите список.')
    if item['status']=='closed': raise ValueError('Учебный разбор уже завершён')
    note=app.field(body,'note',5,1500)
    if route=='/api/incidents/update':
        if not dispatcher(app,profile): raise app.Denied('Статус меняет только учебный диспетчер')
        status=body.get('status')
        allowed={'saved':('review','clarify','closed'),'review':('review','clarify','closed'),'clarify':('review','clarify','closed')}
        if status not in allowed[item['status']]: raise ValueError('Недоступный статус')
    elif route=='/api/incidents/comment': status=item['status']
    else: raise ValueError('Неизвестное действие')
    if not db.execute('UPDATE incidents SET status=?,version=version+1,updated=CURRENT_TIMESTAMP WHERE id=? AND version=?',(status,item['id'],item['version'])).rowcount: raise ValueError('Обращение уже изменено. Обновите список.')
    db.execute('INSERT INTO incident_events(incident_id,author,status,note) VALUES(?,?,?,?)',(item['id'],profile,status,note))
    # Sensitive contents never enter bot notifications or communal feeds.
    author=db.execute('SELECT author FROM incidents WHERE id=?',(item['id'],)).fetchone()[0]
    if app.MODE=='max' and profile!=author and author.startswith('max:') and author[4:].isdigit():
        db.execute('INSERT INTO app_outbox(user_id,text) VALUES(?,?)',(int(author[4:]),f'Обновлено ваше учебное обращение №{item["id"]}. Подробности — «Учебные обращения» в боте или приватный раздел приложения. Это не сообщение от 112.'))
    return {'ok':True,'incident_id':item['id']}
