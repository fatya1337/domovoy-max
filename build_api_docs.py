"""Generate OpenAPI 3.1 for the implemented HTTP surface (no runtime secrets)."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
S=lambda n=0,m=2000:{'type':'string','minLength':n,'maxLength':m}
I={'type':'integer','minimum':1}
B={'type':'boolean'}
def obj(props,required=()):return {'type':'object','properties':props,'required':list(required)}
def arr(items):return {'type':'array','items':items}
def enum(*items):return {'type':'string','enum':list(items)}
def ref(name):return {'$ref':'#/components/schemas/'+name}
status=enum('new','work','done','confirmed')
incident_status=enum('saved','review','clarify','closed')
profile=obj({'id':S(),'name':S(),'role':enum('resident','manager','dispatcher'),'label':S()},('id','name','role','label'))
event=obj({'status':incident_status,'note':S(),'created':S(),'actor':enum('Заявитель','Учебный диспетчер')},('status','note','created','actor'))
schemas={
 'Error':obj({'error':S()},('error',)),
 'OK':obj({'ok':{'const':True}},('ok',)),
 'Profile':profile,
 'Entrance':obj({'id':I,'house_id':I,'number':I,'name':S(),'address':S(),'code':S()},('id','house_id','number','name','address')),
 'Ticket':obj({'id':I,'entrance_id':I,'author':S(),'title':S(),'status':status,'category':S(),'details':S(),'created':S()},('id','entrance_id','author','title','status','category','details','created')),
 'Incident':obj({'id':I,'address':S(),'description':S(),'status':incident_status,'version':I,'created':S(),'updated':S(),'events':arr(event)},('id','address','description','status','version','created','updated','events')),
 'IncidentList':obj({'dispatcher':B,'incidents':arr(ref('Incident')),'counts':{'type':'object','additionalProperties':{'type':'integer','minimum':0}}},('dispatcher','incidents','counts')),
 'State':obj({'profile':ref('Profile'),'profiles':arr(ref('Profile')),'entrances':arr(ref('Entrance')),'selected':{'type':['integer','null']},'demo':B,'training_incidents':B,'dispatcher':B,'outages':arr({'type':'object'}),'messages':arr({'type':'object'}),'notices':arr({'type':'object'}),'tickets':arr(ref('Ticket')),'members':arr(ref('Profile')),'stats':{'type':'object'}},('profile','entrances','selected','demo','training_incidents','dispatcher','outages','messages','notices','tickets','members','stats')),
 'TicketDetail':obj({'ticket':ref('Ticket'),'outage':{'type':['object','null']},'events':arr({'type':'object'}),'profiles':arr(ref('Profile'))},('ticket','events','profiles')),
 'Queue':obj({'tickets':arr(ref('Ticket')),'counts':{'type':'object'},'profiles':arr(ref('Profile'))},('tickets','counts','profiles')),
}
paths={}
def response(schema,description='Успешно'):
 return {'description':description,'content':{'application/json':{'schema':schema}}}
def endpoint(path,method,summary,schema,body=None,required=(),params=None,public=False,description=''):
 operation={'summary':summary,'description':description,'operationId':method+'_'+path.strip('/').replace('/','_'),'responses':{'200':response(schema),'400':response(ref('Error'),'Некорректные данные, устаревшая версия или конфликт request_id'),'403':response(ref('Error'),'Нет доступа, неверная подпись, Host или Origin')}}
 if public:operation['security']=[]
 if params:operation['parameters']=params
 if method=='post':
  props={**body,'request_id':{'type':'string','minLength':16,'maxLength':80,'pattern':'^[A-Za-z0-9_-]+$','description':'Один идентификатор на логическую операцию; повтор с другим телом отклоняется'}}
  operation['requestBody']={'required':True,'content':{'application/json':{'schema':obj(props,required)}}}
 paths.setdefault(path,{})[method]=operation
q=lambda key,required=False:{'name':key,'in':'query','required':required,'schema':I}
endpoint('/health','get','Проверка процесса',ref('OK'),public=True)
endpoint('/api/config','get','Режим приложения',obj({'mode':enum('demo','max')},('mode',)),public=True)
endpoint('/api/state','get','Доступный подъезд и общая лента',ref('State'),params=[q('entrance_id')],description='Житель: только свои подъезды. УК: все дома экземпляра. Приватные обращения отсутствуют в ответе. Лимиты: 100 сообщений, 30 объявлений, 50 заявок, 30 аварий.')
endpoint('/api/ticket','get','Карточка бытовой заявки',ref('TicketDetail'),params=[q('id',True)])
endpoint('/api/queue','get','Очередь УК',ref('Queue'),description='Только ADMIN_IDS; до 100 незакрытых заявок. Счётчики по всей базе.')
endpoint('/api/incidents','get','Приватные учебные обращения',ref('IncidentList'),description='Только автор или DISPATCHER_IDS. В MAX требуется TRAINING_INCIDENTS_ENABLED=1. До 50 карточек; счётчики по всем доступным. УК не получает право чтения чужих обращений.')
result=lambda key:obj({'ok':{'const':True},key:I},('ok',key))
mutations=[
('/api/houses','Создать дом',{'name':S(2,80),'address':S(5,160),'count':{'type':'integer','minimum':1,'maximum':20}},('name','address','count'),obj({'entrance_id':I},('entrance_id',))),
('/api/join','Вступить по приглашению',{'code':S(3,40)},('code',),obj({'entrance_id':I},('entrance_id',))),
('/api/invite/rotate','Заменить приглашение',{'entrance_id':I},('entrance_id',),obj({'code':S(),'entrance_id':I},('code','entrance_id'))),
('/api/messages','Сообщение соседям',{'entrance_id':I,'text':S(1,1000)},('entrance_id','text'),ref('OK')),
('/api/tickets','Создать бытовую заявку',{'entrance_id':I,'title':S(5,300),'category':enum('light','water','clean','lift','door','other'),'details':S(0,2000),'outage_id':{'type':['integer','null'],'minimum':1}},('entrance_id','title'),result('ticket_id')),
('/api/ticket/outage','Связать заявку с аварией',{'entrance_id':I,'id':I,'outage_id':{'type':['integer','null'],'minimum':1}},('entrance_id','id','outage_id'),ref('OK')),
('/api/ticket/comment','Комментарий к бытовой заявке',{'entrance_id':I,'id':I,'text':S(1,1500)},('entrance_id','id','text'),ref('OK')),
('/api/status','Изменить статус бытовой заявки',{'entrance_id':I,'id':I,'status':status,'note':S(0,1500)},('entrance_id','id','status'),ref('OK')),
('/api/notices','Объявление УК',{'entrance_id':I,'title':S(3,100),'text':S(5,1500),'scope':enum('entrance','house')},('entrance_id','title','text'),obj({'ok':{'const':True},'entrances':I},('ok','entrances'))),
('/api/notice/read','Подтвердить ознакомление',{'entrance_id':I,'id':I},('entrance_id','id'),ref('OK')),
('/api/outages','Общая авария домов',{'house_ids':{'type':'array','minItems':1,'maxItems':20,'items':I},'service':enum('water','power','heating','other'),'title':S(5,120),'reason':S(5,1000),'forecast':S(0,120)},('house_ids','service','title','reason'),result('outage_id')),
('/api/outages/update','Обновить аварию',{'id':I,'version':I,'status':enum('reported','work','restored'),'note':S(5,1000),'forecast':S(0,120)},('id','version','status','note'),result('outage_id')),
('/api/incidents','Создать учебное обращение',{'address':S(5,240),'description':S(10,2000),'training_ack':{'const':True}},('address','description','training_ack'),result('incident_id')),
('/api/incidents/update','Учебный статус диспетчера',{'id':I,'version':I,'status':enum('review','clarify','closed'),'note':S(5,1500)},('id','version','status','note'),result('incident_id')),
('/api/incidents/comment','Приватное уточнение',{'id':I,'version':I,'note':S(5,1500)},('id','version','note'),result('incident_id')),
]
for path,title,body,required,result_schema in mutations:
 endpoint(path,'post',title,result_schema,body,required,description='В MAX обязателен Origin, равный PUBLIC_ORIGIN, и валидный X-Max-Init-Data. Content-Type строго application/json. Права и переходы проверяются сервером; описание в API.md.')
paths['/webhook']={'post':{'summary':'Приём событий MAX (альтернатива Long Polling)','operationId':'post_webhook','security':[{'MaxWebhookSecret':[]}],'requestBody':{'required':True,'content':{'application/json':{'schema':{'type':'object','required':['update_type'],'properties':{'update_type':S()}}}}},'responses':{'200':response(ref('OK')),'400':response(ref('Error')),'403':response(ref('Error')),'404':response(ref('Error'))}}}
doc={'openapi':'3.1.0','info':{'title':'Домовой HTTP API','version':'0.3.0','description':'Рабочий прототип одной УК и отдельного учебного диспетчера. Нет внешнего подключения 112. Публичный постоянный адрес ещё не назначен.'},'servers':[{'url':'http://127.0.0.1:8765','description':'Только локальное демо; для MAX заменить фактическим PUBLIC_ORIGIN'}],'security':[{'MaxInitData':[]},{'DemoProfile':[]}],'paths':paths,'components':{'schemas':schemas,'securitySchemes':{'MaxInitData':{'type':'apiKey','in':'header','name':'X-Max-Init-Data','description':'Подписанный MAX initData, срок 1 час. Серверная проверка HMAC; роли из окружения сервера.'},'DemoProfile':{'type':'apiKey','in':'header','name':'X-Demo-Profile','description':'Только APP_MODE=demo: anna, boris, manager, dispatcher. В MAX этот заголовок не даёт доступ.'},'MaxWebhookSecret':{'type':'apiKey','in':'header','name':'X-Max-Bot-Api-Secret'}}}}
(ROOT/'openapi.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
print('Generated',sum(len(v) for v in paths.values()),'operations')
