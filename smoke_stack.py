"""Clean-volume Compose check. Synthetic bot transport; no real MAX calls or live volumes."""
import json
import copy
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import yaml

ROOT=Path(__file__).resolve().parent
PROBE='''import bot,miniapp,connected_bot
from contextlib import closing
miniapp.init()
with closing(bot.connect('/app/data/bot.sqlite3')) as transport, closing(miniapp.connection()) as db:
    with transport:transport.execute('INSERT INTO outbox(user_id,body) VALUES(?,?)',(1,'{"text":"Synthetic restore check"}'))
    def say(uid,text):
        with db:return connected_bot.conversation(db,'max:'+str(uid),text)
    with db:
        result=miniapp.mutate(db,'max:99','/api/houses',{'name':'Учебный дом','address':'Тестоград, Учебная, 10','count':2})
    code=db.execute('SELECT code FROM entrances WHERE id=?',(result['entrance_id'],)).fetchone()[0]
    say(1,'Вступить по коду');say(1,code)
    with db:miniapp.mutate(db,'max:99','/api/outages',{'house_ids':[1],'service':'power','title':'Учебное отключение света','reason':'Проверка восстановления'})
    for text in ['Новая заявка','Освещение','Лампа на третьем этаже не горит','Связать с аварией №1','Подтвердить заявку']:say(1,text)
    say(99,'/status 1 work');say(99,'/status 1 done');say(1,'/confirm 1')
    assert miniapp.state(db,'max:1')['tickets'][0]['status']=='confirmed'
    for text in ['Новое учебное обращение','Понимаю, это учебный режим','Тестоград, Учебная, 10','Вымышленный сценарий проверки','Сохранить учебное обращение']:say(1,text)
    say(22,'/incident_status 1 closed');say(22,'Учебный разбор завершён')
    assert db.execute('SELECT status FROM incidents').fetchone()[0]=='closed'
print('PASS shared bot/application workflows',flush=True)
'''

def main():
    scratch=ROOT/'data'/'stack-check';scratch.mkdir(parents=True,exist_ok=True)
    project='domovoy-check-'+uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(dir=scratch) as td:
        folder=Path(td)
        spec=yaml.safe_load((ROOT/'compose.max.yaml').read_text())
        env={'APP_MODE':'max','MINIAPP_DATABASE_PATH':'/app/data/pilot.sqlite3','DATABASE_PATH':'/app/data/bot.sqlite3','PUBLIC_ORIGIN':'https://stack.example.test','MAX_BOT_TOKEN':'synthetic-stack-test-token','ADMIN_IDS':'99','DISPATCHER_IDS':'22','TRAINING_INCIDENTS_ENABLED':'1','MINIAPP_ENABLED':'0'}
        for key in ('app','bot','backup'):
            service=spec['services'][key];service['build']['context']=str(ROOT)
            service.pop('env_file',None);service['environment']=env if key!='backup' else {}
            service['restart']='no'
        spec['services']['app']['image']=project+'-app:qa'
        spec['volumes']['restore-data']={}
        restore_copy=folder/'restore_copy.py'
        restore_copy.write_text('''import backup,shutil,os
from pathlib import Path
folder=Path('/backups')/Path('/backups/restore-source.txt').read_text().strip()
assert backup.verify(folder)==2
for name in ('pilot.sqlite3','bot.sqlite3'):
    target=Path('/app/data')/name
    assert not target.exists(), 'Restore destination must be empty'
    shutil.copyfile(folder/name,target)
    target.chmod(0o600)
print('PASS copied verified snapshot into a new isolated volume')
''')
        spec['services']['restore-copy']={'image':project+'-app:qa','profiles':['restore'],
            'command':['python','/app/restore_copy.py'],
            'volumes':['restore-data:/app/data','backup-data:/backups:ro',str(restore_copy)+':/app/restore_copy.py:ro']}
        restored=copy.deepcopy(spec['services']['app'])
        restored.pop('build',None);restored['profiles']=['restore'];restored['volumes']=['restore-data:/app/data']
        spec['services']['restore-app']=restored
        probe=folder/'probe.py';probe.write_text(PROBE)
        spec['services']['bot']['command']=['python','/app/probe.py']
        spec['services']['bot']['volumes'].append(str(probe)+':/app/probe.py:ro')
        spec['services']['backup']['command']=['python','backup.py','--loop','--interval','60']
        caddy=folder/'Caddyfile';caddy.write_text(':80 {\n reverse_proxy app:8765\n}\n')
        spec['services']['https'].update({'environment':{},'restart':'no','ports':[],'volumes':[str(caddy)+':/etc/caddy/Caddyfile:ro','caddy-data:/data','caddy-config:/config']})
        spec['networks']={'default':{'internal':True}}
        config=folder/'compose.json';config.write_text(json.dumps(spec))
        command=['docker','compose','-p',project,'-f',str(config)]
        def run(*args,timeout=60):
            result=subprocess.run(command+list(args),cwd=folder,text=True,capture_output=True,timeout=timeout)
            if result.returncode:raise RuntimeError(result.stdout+'\n'+result.stderr)
            return result.stdout.strip()
        try:
            run('up','-d','--build',timeout=240)
            run('exec','-T','app','python','-c',"import urllib.request,json; req=urllib.request.Request('http://https/health',headers={'Host':'stack.example.test'}); assert json.load(urllib.request.urlopen(req,timeout=10))['ok']")
            subprocess.run(command+['wait','bot'],cwd=folder,capture_output=True,timeout=60)
            cid=run('ps','-a','-q','bot')
            exit_code=subprocess.check_output(['docker','inspect',cid,'--format','{{.State.ExitCode}}'],text=True).strip()
            if exit_code!='0':raise RuntimeError(run('logs','bot'))
            print('PASS: clean Compose app + bot workflows + Caddy HTTP',flush=True)
            # Ask the actual backup image to make and verify a fresh snapshot after bot completion.
            result=run('exec','-T','backup','python','-c',"import backup; p=backup.snapshot(['/app/data/pilot.sqlite3','/app/data/bot.sqlite3'],'/backups'); assert backup.verify(p)==2; (p.parent/'restore-source.txt').write_text(p.name); print('PASS: two database backups verified')")
            print(result,flush=True)
            run('exec','-T','app','python','-c',"import urllib.request,urllib.error; req=urllib.request.Request('http://https/api/state',headers={'Host':'stack.example.test','X-Demo-Profile':'manager'});\ntry:\n urllib.request.urlopen(req,timeout=5); raise AssertionError('Demo identity accepted')\nexcept urllib.error.HTTPError as exc:\n assert exc.code==403")
            print('PASS: unsigned demo identity rejected',flush=True)
            print(run('run','--rm','--no-deps','restore-copy'),flush=True)
            run('up','-d','--wait','restore-app',timeout=90)
            run('exec','-T','restore-app','python','-c',"import miniapp,bot; from contextlib import closing; db=miniapp.connection(); info=miniapp.ticket_detail(db,'max:1',1); assert info['ticket']['status']=='confirmed'; assert info['outage']['id']==1; assert len(info['events'])>=5; assert db.execute('SELECT status FROM incidents').fetchone()[0]=='closed'; db.close(); transport=bot.connect('/app/data/bot.sqlite3'); assert transport.execute('SELECT count(*) FROM outbox WHERE user_id=1').fetchone()[0]==1; transport.close()")
            print('PASS: restored app is healthy; ticket, outage, history, private case and transport outbox survived',flush=True)
        finally:
            # Only this randomly named test project and its synthetic volumes are deleted.
            subprocess.run(command+['--profile','*','down','-v','--remove-orphans'],cwd=folder,capture_output=True,timeout=60,check=True)

if __name__=='__main__':main()
