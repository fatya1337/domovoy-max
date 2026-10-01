"""Run isolated Docker checks using synthetic credentials only. Never touches the live bot."""
import http.client
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def main():
    name = 'domovoy-http-check'
    try:
        subprocess.run(['docker','run','--rm','-d','--name',name,
            '-p','127.0.0.1:18765:8765','-e','APP_MODE=max',
            '-e','MAX_BOT_TOKEN=synthetic-smoke-token',
            '-e','PUBLIC_ORIGIN=https://app.example.test',
            '-e','MAX_WEBHOOK_SECRET=synthetic-webhook-secret',
            '-e','MINIAPP_DATABASE_PATH=/app/data/smoke.sqlite3',
            'domovoy-pilot:local'],check=True,capture_output=True,timeout=20)
        for attempt in range(30):
            try:
                request=urllib.request.Request('http://127.0.0.1:18765/health',headers={'Host':'app.example.test'})
                with urllib.request.urlopen(request,timeout=2) as response:
                    assert response.status==200 and json.load(response)['ok']
                print('PASS: container HTTP health',flush=True)
                break
            except (urllib.error.URLError,http.client.RemoteDisconnected,ConnectionResetError):
                if attempt==29:raise
                time.sleep(.2)
        request=urllib.request.Request('http://127.0.0.1:18765/api/state',headers={'Host':'app.example.test','X-Demo-Profile':'manager'})
        try:
            urllib.request.urlopen(request,timeout=2)
            raise AssertionError('Demo impersonation accepted')
        except urllib.error.HTTPError as exc:
            assert exc.code==403
            print('PASS: demo impersonation rejected',flush=True)
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=10)
    name='domovoy-caddy-check'
    try:
        result=subprocess.run(['docker','run','--rm','--name',name,'--network','none',
            '-e','APP_DOMAIN=app.example.test','-v',str(Path(__file__).parent/'Caddyfile')+':/etc/caddy/Caddyfile:ro',
            'caddy:2.10.2-alpine','caddy','validate','--config','/etc/caddy/Caddyfile','--adapter','caddyfile'],
            capture_output=True,text=True,timeout=20)
        if result.returncode:
            raise RuntimeError(result.stderr)
        print('PASS: Caddy configuration',flush=True)
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=10)


if __name__=='__main__':main()
