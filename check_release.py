"""Read-only checks of an explicitly supplied Domovoy deployment. No credentials."""
import argparse
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

MAX_RESPONSE = 2_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def origin(value):
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname and
                 not parsed.username and not parsed.password and
                 parsed.path in ('', '/') and not parsed.query and not parsed.fragment and
                 parsed.port in (None, 443))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Укажите корневой HTTPS-адрес без логина, пути, query и fragment')
    return value.rstrip('/')


def fetch(url):
    request = Request(url, headers={'User-Agent': 'Domovoy-release-check/1.0'})
    try:
        response = build_opener(NoRedirect()).open(request, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError('Ответ превышает допустимый размер')
        return response.status, response.headers, body


def check(base, get=fetch):
    base = origin(base)
    results = []
    routes = [('/health', 'application/json', {'ok': True}),
              ('/api/config', 'application/json', {'mode': 'max'}),
              ('/', 'text/html', None), ('/app.js', 'text/javascript', None),
              ('/style.css', 'text/css', None), ('/request.js', 'text/javascript', None)]
    for path, mime, expected in routes:
        try:
            status, headers, body = get(base + path)
            if status != 200:
                raise ValueError(f'HTTP {status}; ожидается 200 без перенаправления')
            if headers.get('Content-Type', '').split(';')[0].strip() != mime:
                raise ValueError('Неверный Content-Type')
            if not body.strip():
                raise ValueError('Пустой ответ')
            if expected is not None and json.loads(body) != expected:
                raise ValueError('Неожиданный ответ или включён демонстрационный режим')
            if path == '/':
                page = body.decode('utf-8')
                if 'Домовой' not in page or '/app.js' not in page or '/style.css' not in page or '/request.js' not in page:
                    raise ValueError('По адресу открывается другая страница')
                if not headers.get('Content-Security-Policy'):
                    raise ValueError('Нет Content-Security-Policy')
            results.append((path, True, 'OK'))
        except (OSError, URLError, ValueError) as exc:
            # Do not echo response bodies, redirect destinations or exception URLs.
            reason = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Ошибка сети, TLS или формата ответа'
            results.append((path, False, reason))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='Постоянный HTTPS-адрес вашего приложения')
    args = parser.parse_args()
    try:
        results = check(args.url)
    except ValueError as exc:
        print(str(exc)); return 1
    for path, ok, message in results:
        print(f'{"PASS" if ok else "FAIL"} {path}: {message}')
    print('Проверка не подтверждает привязку в MAX, доставку сообщений или сценарии реальных пользователей.')
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
