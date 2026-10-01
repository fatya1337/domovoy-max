"""Local-only disposable browser QA server for interrupted responses.

Run this script, then open its printed localhost URL. Control flags live in the
printed temporary JSON file. Never use with real profiles or a production DB.
The temporary database is deleted on normal shutdown; the production app and bot
are not affected. Flags: drop_ticket_replies, fail_reads_after_write.
"""
import json
from pathlib import Path
import tempfile
from http.server import ThreadingHTTPServer
import miniapp as app


def main():
    if app.MODE != 'demo':
        raise SystemExit('Only APP_MODE=demo is permitted for this disposable test')
    (app.ROOT/'data').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='network-qa-', dir=app.ROOT/'data') as folder:
        control=Path(folder)/'control.json'
        control.write_text('{}')
        app.DB=Path(folder)/'test.sqlite3'
        app.init(app.DB)
        original_connection=app.connection
        app.connection=lambda:original_connection(app.DB)
        class Handler(app.Handler):
            def safe_host(self):
                return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

            def do_POST(self):
                if self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}':
                    return self.respond(403, {'error':'QA origin mismatch'})
                self.headers.replace_header('Origin','http://127.0.0.1:8765')
                return super().do_POST()

            def respond(self, code, value, mime='application/json; charset=utf-8'):
                try: flags=json.loads(control.read_text())
                except (OSError,ValueError): flags={}
                if self.command=='POST' and code==200:
                    self.server.saved_write=True
                    if self.path=='/api/tickets' and flags.get('drop_ticket_replies'):
                        self.close_connection=True
                        return
                if (self.command=='GET' and self.path.startswith(('/api/state','/api/ticket'))
                        and self.server.saved_write and flags.get('fail_reads_after_write')):
                    return super().respond(503,{'error':'Synthetic QA outage'})
                return super().respond(code,value,mime)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.saved_write=False
        print(f'Local disposable QA: http://127.0.0.1:{server.server_port}/',flush=True)
        print(f'Control file: {control}',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()


if __name__=='__main__':main()
