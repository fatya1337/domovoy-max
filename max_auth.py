"""MAX initData validation. Never trust initDataUnsafe or client-provided roles."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl


def validate_init_data(raw, token, now=None, max_age=3600):
    if not isinstance(raw, str) or not raw or len(raw) > 16384 or not token:
        raise ValueError('Откройте приложение из бота MAX')
    if re.search(r'%(?![0-9a-fA-F]{2})', raw):
        raise ValueError('Некорректное кодирование входа')
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, errors='strict', max_num_fields=32)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError('Повторяющиеся параметры входа')
        supplied = fields.pop('hash')
        if not re.fullmatch('[0-9a-f]{64}', supplied):
            raise ValueError('Неверная подпись входа')
        secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        check = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError('Неверная подпись входа')
        age = (time.time() if now is None else now) - int(fields['auth_date'])
        if age < -30 or age > max_age:
            raise ValueError('Вход устарел. Закройте и снова откройте приложение в MAX')
        user = json.loads(fields['user'])
        uid = user['id']
        if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
            raise ValueError('Некорректный пользователь')
        name = user.get('first_name')
        if not isinstance(name, str) or not name.strip():
            name = 'Житель'
        return {'id': f'max:{uid}', 'name': name.strip()[:80]}
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Не удалось проверить вход MAX') from None
