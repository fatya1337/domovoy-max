"""MAX conversation flow backed by the same application database as the miniapp."""
import json
import os
import re
from contextlib import closing
import miniapp
import incidents

LABELS = {'new':'Новая', 'work':'В работе', 'done':'Ждёт подтверждения', 'confirmed':'Решена'}
CATEGORIES = {'Освещение':'light','Вода и отопление':'water','Уборка':'clean','Лифт':'lift','Двери и домофон':'door','Другое':'other'}


def menu(manager=False):
    return ['Мой дом','Новая заявка','Мои заявки','Аварии дома','Объявления'] + (['Очередь УК','Добавить дом'] if manager else ['Вступить по коду']) + ['Помощь','Экстренная помощь']


def body(text, buttons):
    rows = [[{'type':'message','text':label} for label in buttons[i:i+2]] for i in range(0,len(buttons),2)]
    if os.environ.get('MINIAPP_ENABLED') == '1':
        rows.insert(0,[{'type':'open_app','text':'Открыть Домового','web_app':os.environ.get('MAX_BOT_USERNAME','t738_hakaton_max_bot')}])
    return {'text':text[:3900], 'attachments':[{'type':'inline_keyboard','payload':{'buttons':rows}}]}


def set_session(db, profile, stage, payload):
    db.execute('INSERT INTO bot_sessions(profile,stage,payload) VALUES(?,?,?) ON CONFLICT(profile) DO UPDATE SET stage=excluded.stage,payload=excluded.payload', (profile,stage,json.dumps(payload,ensure_ascii=False)))


def conversation(db, profile, text):
    command=text.strip().casefold()
    manager=miniapp.is_manager(profile)
    main=menu(manager)
    if incidents.enabled(miniapp):main.insert(0,'Учебные обращения')
    row=db.execute('SELECT * FROM bot_sessions WHERE profile=?',(profile,)).fetchone()
    stage=row['stage'] if row else 'idle'
    payload=json.loads(row['payload']) if row else {}
    def answer(text,buttons=None): return body(text,main if buttons is None else buttons)
    def save(stage,**values):
        payload.update(values);set_session(db,profile,stage,payload)
    def reset():
        keep={'entrance_id':payload['entrance_id']} if 'entrance_id' in payload else {}
        set_session(db,profile,'idle',keep)
    def selected():
        state=miniapp.state(db,profile)
        ids={e['id'] for e in state['entrances']}
        eid=payload.get('entrance_id')
        if eid not in ids:eid=state['selected']
        if eid is None:raise ValueError('Сначала выберите «Добавить дом».' if manager else 'Сначала вступите в подъезд: нажмите «Вступить по коду». Код выдаёт ваша УК.')
        payload['entrance_id']=eid
        return eid
    def summary(t):return f'№{t["id"]} · {LABELS[t["status"]]}\n{t["title"]}'
    cancel=['Отмена','Экстренная помощь']
    if command in ('/start','меню','/cancel','отмена'):
        reset()
        if command in ('/cancel','отмена'):return answer('Черновик отменён. Сохранённые заявки остались на месте.')
        return answer('🏡 Домовой — ваш дом на связи\n\nЗаявки, объявления и вопросы подъезда — здесь и в миниаппе, в одной базе.\n\n'+('Вы вошли как сотрудник УК. Добавьте дом или откройте очередь обращений.' if manager else 'Начните с приглашения УК: вступите в свой подъезд по коду. После этого адрес не нужно вводить заново.')+'\n\nЭто пилот проекта. Экстренные службы и государственные системы не подключены.')
    if command in ('/help','помощь'):
        return answer('Как пользоваться Домовым\n\n1. Вступите по коду УК и выберите дом.\n2. «Новая заявка» — категория, описание, проверка и отправка.\n3. «Мои заявки» — статус и история.\n4. После выполнения подтвердите результат или верните заявку.\n\n/ticket НОМЕР — карточка\n/comment НОМЕР текст — комментарий\n/confirm НОМЕР — всё исправлено\n/reopen НОМЕР — проблема осталась\n/home НОМЕР — выбрать подъезд из «Мой дом»\n/archive — прежние демозаявки\n\n'+('УК: /status НОМЕР work или done.\n' if manager else '')+'«Отмена» убирает только текущий черновик.\nБот не вызывает 112. При непосредственной опасности звоните 112 с телефона.')
    if command in ('учебные обращения','/incidents'):
        info=incidents.listing(miniapp,db,profile)
        reset()
        rows=info['incidents'][:6]
        return answer('Учебный режим · не связь с 112\n\n'+('Очередь учебного диспетчера' if info['dispatcher'] else 'Ваши приватные учебные обращения')+'\n\n'+('\n'.join(f'№{i["id"]} · {incidents.STATUSES[i["status"]]}' for i in rows) or 'Пока нет обращений.')+'\n\nИспользуйте вымышленные данные. При реальной опасности звоните 112. Веб-кабинет и бот используют общую историю.',[f'/incident {i["id"]}' for i in rows]+([] if info['dispatcher'] else ['Новое учебное обращение'])+['Меню'])
    if command in ('новое учебное обращение','/incident_new'):
        incidents.check(miniapp)
        reset();save('incident_ack')
        return answer('Это учебная демонстрация. Сообщение не попадёт в 112, полицию или МЧС и не вызовет помощь. Используйте только вымышленные сведения.\n\nПри реальной опасности звоните 112. Для продолжения подтвердите учебный режим.', ['Понимаю, это учебный режим']+cancel)
    match=re.fullmatch(r'/(incident|incident_reply|incident_status)\s+(\d+)(?:\s+(review|clarify|closed))?',command)
    if match:
        action,iid,status=match[1],int(match[2]),match[3]
        item=incidents.detail(miniapp,db,profile,iid)
        if action=='incident':
            history='\n'.join(f'{e["actor"]}: {e["note"][:180]}' for e in item['events'][-3:])
            buttons=[]
            if item['status']!='closed':
                buttons.append(f'/incident_reply {iid}')
                if incidents.dispatcher(miniapp,profile):buttons += [f'/incident_status {iid} {v}' for v in ('review','clarify','closed')]
            return answer(f'Учебное обращение №{iid}\n{incidents.STATUSES[item["status"]]}\n\n{item["address"]}\n{item["description"][:1800]}\n\n'+history+'\n\nВ 112 не передавалось. При опасности звоните 112.',buttons+['Учебные обращения','Меню'])
        if item['status']=='closed':raise ValueError('Учебный разбор уже завершён')
        if action=='incident_status' and (not incidents.dispatcher(miniapp,profile) or status is None):
            raise miniapp.Denied('Учебный статус меняет только диспетчер: review, clarify или closed.')
        save('incident_note',incident_id=iid,incident_version=item['version'],incident_status=status if action=='incident_status' else None)
        return answer(('Учебный статус: '+incidents.STATUSES[status]+'. ' if action=='incident_status' else '')+'Введите пояснение от 5 до 1500 символов. Его увидят автор и учебный диспетчер.',cancel)
    if stage.startswith('incident_'):
        incidents.check(miniapp)
        if text.startswith('/'):
            return answer('Команда не распознана. Учебный черновик сохранён.',cancel+['Учебные обращения'])
        if stage=='incident_ack':
            if command!='понимаю, это учебный режим':return answer('Подтвердите учебный характер или отмените.', ['Понимаю, это учебный режим']+cancel)
            save('incident_address');return answer('Шаг 1 из 3 · Введите вымышленный адрес (5–240 символов).',cancel)
        if stage=='incident_address':
            save('incident_description',incident_address=miniapp.field({'address':text},'address',5,240))
            return answer('Шаг 2 из 3 · Опишите вымышленную ситуацию (10–2000 символов).',cancel)
        if stage=='incident_description':
            save('incident_confirm',incident_description=miniapp.field({'description':text},'description',10,2000))
            return answer('Шаг 3 из 3 · Проверьте учебное обращение\n\n'+payload['incident_address']+'\n'+payload['incident_description']+'\n\nСохранится только в учебной системе; внешним службам не отправляется.', ['Сохранить учебное обращение']+cancel)
        if stage=='incident_confirm':
            if command!='сохранить учебное обращение':return answer('Подтвердите сохранение или отмените.', ['Сохранить учебное обращение']+cancel)
            result=miniapp.mutate(db,profile,'/api/incidents',{'address':payload['incident_address'],'description':payload['incident_description'],'training_ack':True});reset()
            return answer(f'Учебное обращение №{result["incident_id"]} сохранено. Это не приём сообщения службой 112.',[f'/incident {result["incident_id"]}','Учебные обращения','Меню'])
        if stage=='incident_note':
            status=payload.get('incident_status')
            result=miniapp.mutate(db,profile,'/api/incidents/update' if status else '/api/incidents/comment',{'id':payload['incident_id'],'version':payload['incident_version'],'status':status,'note':text});reset()
            return answer('Учебная история обновлена.',[f'/incident {result["incident_id"]}','Учебные обращения','Меню'])
    if command in ('вступить по коду','/join'):
        if manager:return answer('Вы уже видите все дома вашей организации. Откройте «Мой дом».')
        save('join');return answer('Введите код приглашения вашего подъезда, полученный от УК.',cancel)
    if command in ('добавить дом','/house'):
        if not manager:raise miniapp.Denied('Добавлять дома может только УК.')
        save('house_name');return answer('Как назвать дом? Например: «Соседи у парка».',cancel)
    if command in ('мой дом','/home'):
        state=miniapp.state(db,profile)
        if not state['entrances']:return answer('Домов пока нет. '+('Нажмите «Добавить дом».' if manager else 'Нажмите «Вступить по коду».'))
        lines=[]
        for e in state['entrances'][:12]:
            lines.append(f'{e["address"]} · подъезд {e["number"]}\nВыбрать: /home {e["id"]}'+(f'\nПриглашение: {e["code"]}' if manager else ''))
        return answer('Ваши дома\n\n'+'\n\n'.join(lines))
    match=re.fullmatch(r'/home\s+(\d+)',command)
    if match:
        eid=int(match[1]);miniapp.access(db,profile,eid);save('idle',entrance_id=eid)
        e=next(e for e in miniapp.state(db,profile,eid)['entrances'] if e['id']==eid)
        return answer(f'Выбран дом: {e["address"]}, подъезд {e["number"]}.\nЗаявки и объявления относятся к этому подъезду.')
    if command in ('новая заявка','/new'):
        eid=selected();save('category',entrance_id=eid,title='',category='other',outage_id=None)
        return answer('Шаг 1 из 3 · Что нужно исправить?',list(CATEGORIES)+cancel)
    if command in ('мои заявки','/my','очередь ук','/queue'):
        is_queue=command in ('очередь ук','/queue')
        if is_queue:rows=miniapp.manager_queue(db,profile)['tickets'][:6]
        else:rows=db.execute('SELECT * FROM tickets WHERE author=? ORDER BY id DESC LIMIT 6',(profile,)).fetchall()
        if not rows:return answer('Очередь пуста.' if is_queue else 'У вас пока нет заявок. Нажмите «Новая заявка».')
        return answer(('Очередь УК' if is_queue else 'Ваши последние заявки')+'\n\n'+'\n\n'.join(summary(t) for t in rows),[f'/ticket {t["id"]}' for t in rows]+['Меню'])
    if command in ('аварии дома','/outages'):
        outages=miniapp.house_outages(db,profile,selected())
        active=[o for o in outages if o['status']!='restored'][:3]
        if not active:return answer('В системе нет опубликованных активных аварий для вашего дома. Это не гарантия отсутствия проблемы: при необходимости создайте заявку.')
        blocks=[]
        for o in active:
            latest=o['history'][0]['note'] if o['history'] else o['reason']
            blocks.append(f'№{o["id"]} · {o["title"]}\n{miniapp.OUTAGE_STATUSES[o["status"]]}\nПричина: {o["reason"][:300]}\nПоследнее сообщение: {latest[:300]}\nПрогноз (не гарантия): {o["forecast"] or "Срок уточняется"}\nИсточник: {o["source"]}\nОбновлено: {o["updated"]} UTC')
        return answer('Аварии выбранного дома\n\n'+'\n\n'.join(blocks))
    if command in ('объявления','/notices'):
        state=miniapp.state(db,profile,selected())
        notices=state['notices'][:3]
        return answer('Объявлений пока нет.' if not notices else 'Объявления выбранного подъезда\n\n'+'\n\n'.join(f'{n["title"]}\n{n["text"][:700]}' for n in notices))
    friendly=re.fullmatch(r'(взять в работу|работа выполнена|всё исправлено|проблема осталась|комментарий к заявке) №(\d+)',command)
    if friendly:
        label,tid=friendly[1],int(friendly[2])
        item=miniapp.ticket_detail(db,profile,tid)['ticket']
        if label in ('взять в работу','работа выполнена') and not manager:
            raise miniapp.Denied('Менять рабочие статусы может только УК.')
        if label in ('всё исправлено','проблема осталась') and (item['author']!=profile or item['status']!='done'):
            raise miniapp.Denied('Подтвердить или вернуть можно только свою выполненную заявку.')
        if label in ('работа выполнена','проблема осталась','комментарий к заявке'):
            if label=='работа выполнена' and item['status']!='work':raise ValueError('Сначала возьмите заявку в работу.')
            action={'работа выполнена':'done','проблема осталась':'work','комментарий к заявке':'comment'}[label]
            save('ticket_note',note_ticket_id=tid,note_action=action)
            prompt={'done':'Расскажите, что было сделано. Житель увидит отчёт и сможет подтвердить результат.',
                    'work':'Что осталось исправить? Ваше пояснение увидит управляющая компания.',
                    'comment':'Напишите комментарий. Его увидят УК и участники подъезда.'}[action]
            return answer(f'Заявка №{tid} · {item["title"]}\n\n'+prompt+' От 1 до 1500 символов.',cancel)
        text=f'/status {tid} work' if label=='взять в работу' else f'/confirm {tid}'
        command=text.casefold()
    if stage=='ticket_note' and not text.startswith('/'):
        tid=payload['note_ticket_id'];action=payload['note_action']
        item=miniapp.ticket_detail(db,profile,tid)['ticket']
        note=miniapp.field({'note':text},'note',1,1500)
        if action=='comment':
            miniapp.mutate(db,profile,'/api/ticket/comment',{'entrance_id':item['entrance_id'],'id':tid,'text':note})
        else:
            miniapp.mutate(db,profile,'/api/status',{'entrance_id':item['entrance_id'],'id':tid,'status':action,'note':note})
        reset()
        return answer(f'Заявка №{tid}: '+('комментарий добавлен.' if action=='comment' else LABELS[action]+'.'),[f'/ticket {tid}','Меню'])
    match=re.fullmatch(r'/(ticket|confirm|reopen|status|comment)\s+(\d+)(?:\s+([\s\S]+))?',text.strip(),re.I)
    if match:
        action,tid,tail=match[1].lower(),int(match[2]),match[3] or ''
        detail=miniapp.ticket_detail(db,profile,tid);t=detail['ticket']
        if action=='ticket':
            e=db.execute('SELECT e.number,h.address FROM entrances e JOIN houses h ON h.id=e.house_id WHERE e.id=?',(t['entrance_id'],)).fetchone()
            history='\n'.join(f'• {LABELS.get(v["status"],"Комментарий" if v["kind"]=="comment" else "Связь с аварией" if v["kind"]=="outage" else "Создана")}'+(f': {v["text"][:180]}' if v['text'] else '') for v in detail['events'][-5:])
            actions=[]
            if manager and t['status'] in ('new','work'):actions=[('Взять в работу' if t['status']=='new' else 'Работа выполнена')+f' №{tid}']
            if t['author']==profile and t['status']=='done':actions=[f'Всё исправлено №{tid}',f'Проблема осталась №{tid}']
            outage=detail.get('outage')
            linked=(f'\n\nОбщая авария №{outage["id"]}: {outage["title"]}\n{miniapp.OUTAGE_STATUSES[outage["status"]]}\nПричина: {outage["reason"][:300]}\nПрогноз: {outage["forecast"] or "не указан"}\nИсточник: {outage["source"]} · {outage["updated"]} UTC\nЗаявка автоматически не закрывается.' if outage else '')
            return answer(summary(t)+f'\n{e["address"]}, подъезд {e["number"]}\n'+t['details']+linked+'\n\n'+history+f'\n\nКомментарий: /comment {tid} ваш текст',actions+[f'Комментарий к заявке №{tid}','Мои заявки','Меню'])
        if action=='comment':
            miniapp.mutate(db,profile,'/api/ticket/comment',{'entrance_id':t['entrance_id'],'id':tid,'text':tail})
            return answer(f'Комментарий к заявке №{tid} сохранён.',[f'/ticket {tid}','Меню'])
        status={'confirm':'confirmed','reopen':'work'}.get(action,tail.strip().lower())
        if action=='status' and not manager:raise miniapp.Denied('Менять рабочие статусы может только УК.')
        if action in ('confirm','reopen') and (t['author']!=profile or t['status']!='done'):raise miniapp.Denied('Подтвердить или вернуть можно только свою выполненную заявку.')
        miniapp.mutate(db,profile,'/api/status',{'entrance_id':t['entrance_id'],'id':tid,'status':status})
        return answer(f'Заявка №{tid}: {LABELS[status]}.',[f'/ticket {tid}','Меню'])
    # A command should never accidentally become the title of a draft.
    if text.startswith('/'):return answer('Команда не распознана. Нажмите «Помощь»; черновик сохранён.',cancel+['Помощь'])
    if stage=='join':
        result=miniapp.mutate(db,profile,'/api/join',{'code':text});save('idle',entrance_id=result['entrance_id'])
        return answer('Вы присоединились к подъезду. Теперь доступны его объявления и заявки.')
    if stage=='house_confirm':return answer('Нажмите «Создать дом» или отмените черновик.', ['Создать дом']+cancel)
    if stage.startswith('house_'):
        if not manager:raise miniapp.Denied('Добавлять дома может только УК.')
        if stage=='house_name':save('house_address',house_name=miniapp.field({'name':text},'name',2,80));return answer('Укажите адрес дома: город, улица, номер.',cancel)
        if stage=='house_address':save('house_count',house_address=miniapp.field({'address':text},'address',5,160));return answer('Сколько подъездов в доме? Введите число от 1 до 20.',cancel)
        if not text.isdecimal():raise ValueError('Введите число подъездов от 1 до 20.')
        count=int(text)
        if not 1<=count<=20:raise ValueError('Введите число от 1 до 20.')
        save('house_confirm',house_count=count)
        return answer(f'Проверьте дом:\n{payload["house_name"]}\n{payload["house_address"]}\nПодъездов: {count}', ['Создать дом']+cancel)
    if stage=='category':
        category=CATEGORIES.get(text)
        if not category:return answer('Выберите категорию кнопкой.',list(CATEGORIES)+cancel)
        save('title',category=category);return answer('Шаг 2 из 3 · Опишите проблему и место, от 5 до 300 символов. Адрес уже выбран из вашего дома.',cancel)
    if stage=='title':
        title=miniapp.field({'title':text},'title',5,300);save('confirm',title=title)
        e=next(e for e in miniapp.state(db,profile,selected())['entrances'] if e['id']==selected())
        active=[o for o in miniapp.house_outages(db,profile,selected()) if o['status']!='restored'][:3]
        known='\n\nУК уже опубликовала аварии:\n'+'\n'.join(f'№{o["id"]}: {o["title"]}' for o in active) if active else ''
        return answer(f'Шаг 3 из 3 · Проверьте заявку\n\n{e["address"]}, подъезд {e["number"]}\n{title}\n\nЗаявку увидят УК и участники подъезда.'+known+'\nПри необходимости выберите связанную аварию или подтвердите без связи.', ['Подтвердить заявку']+[f'Связать с аварией №{o["id"]}' for o in active]+cancel)
    if stage=='confirm' and command.startswith('связать с аварией №'):
        match=re.fullmatch(r'связать с аварией №(\d+)',command)
        if not match:raise ValueError('Выберите аварию кнопкой')
        outage=miniapp.validate_ticket_outage(db,selected(),int(match[1]))
        save('confirm',outage_id=outage['id'])
        return answer(f'Выбрана авария №{outage["id"]}: {outage["title"]}.\nИсточник: УК. Связь не означает автоматического закрытия заявки.',['Подтвердить заявку','Без связи с аварией']+cancel)
    if stage=='confirm' and command=='без связи с аварией':
        save('confirm',outage_id=None);return answer('Связь убрана из черновика.',['Подтвердить заявку']+cancel)
    if stage=='confirm' and command=='подтвердить заявку':
        result=miniapp.mutate(db,profile,'/api/tickets',{'entrance_id':selected(),'title':payload['title'],'category':payload['category'],'outage_id':payload.get('outage_id')});reset()
        return answer(f'✅ Заявка №{result["ticket_id"]} создана. Она уже доступна в общей базе бота и миниаппы.',[f'/ticket {result["ticket_id"]}','Меню'])
    return answer('Выберите действие в меню. Если вы заполняли заявку, продолжите ответом или нажмите «Отмена».')


def respond_connected(botdb, uid, text, event_key=None):
    profile=f'max:{uid}'
    with closing(miniapp.connection()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        cached=db.execute('SELECT body FROM connected_replies WHERE event_id=? AND profile=?',(event_key,profile)).fetchone() if event_key else None
        if cached:result=json.loads(cached['body'])
        else:
            # Names are populated by signed miniapp auth. The bot does not invent an identity.
            db.execute("INSERT OR IGNORE INTO users(id,name) VALUES(?,'Житель')",(profile,))
            db.execute('SAVEPOINT action')
            try:
                session=db.execute('SELECT * FROM bot_sessions WHERE profile=?',(profile,)).fetchone()
                if session and session['stage']=='house_confirm' and text.strip().casefold()=='создать дом':
                    payload=json.loads(session['payload'])
                    created=miniapp.mutate(db,profile,'/api/houses',{'name':payload['house_name'],'address':payload['house_address'],'count':payload['house_count']})
                    set_session(db,profile,'idle',{'entrance_id':created['entrance_id']})
                    result=body('Дом создан. Откройте «Мой дом», чтобы получить приглашения для жителей.',menu(True))
                else:result=conversation(db,profile,text)
            except (ValueError,TypeError,miniapp.Denied) as exc:
                db.execute('ROLLBACK TO action')
                result=body(str(exc) if not isinstance(exc,TypeError) else 'Проверьте введённые данные.', ['Отмена','Помощь','Меню'])
            db.execute('RELEASE action')
            if event_key:db.execute('INSERT INTO connected_replies(event_id,profile,body) VALUES(?,?,?)',(event_key,profile,json.dumps(result,ensure_ascii=False)))
    botdb.execute('INSERT INTO outbox(user_id,body) VALUES(?,?)',(uid,json.dumps(result,ensure_ascii=False)))
