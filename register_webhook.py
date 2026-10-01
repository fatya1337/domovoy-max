"""Run on the pilot host only after HTTPS is reachable and local polling is stopped."""
import os
import re
from urllib.parse import urlparse
from bot import MaxAPI

origin=os.environ.get('PUBLIC_ORIGIN','').rstrip('/')
secret=os.environ.get('MAX_WEBHOOK_SECRET','')
parsed=urlparse(origin)
if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.port not in (None,443):
    raise SystemExit('Set PUBLIC_ORIGIN to the actual HTTPS origin')
if not re.fullmatch(r'[a-zA-Z0-9_-]{32,256}',secret):
    raise SystemExit('Set MAX_WEBHOOK_SECRET to a random 32+ character value')
api=MaxAPI()
existing=api.request('GET','/subscriptions').get('subscriptions',[])
if any(s.get('url')!=origin+'/webhook' for s in existing):
    raise SystemExit('An unrelated Webhook exists; left unchanged')
result=api.request('POST','/subscriptions',body={'url':origin+'/webhook','secret':secret,'update_types':['bot_started','message_created']})
if not result.get('success'):
    raise SystemExit('MAX did not confirm the subscription')
print('Webhook registered successfully')
