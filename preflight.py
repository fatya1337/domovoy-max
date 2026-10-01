"""Validate deployment settings without displaying credentials or modifying MAX."""
import argparse
from pathlib import Path
import re
from urllib.parse import urlparse


def check(values):
    errors=[]
    domain=values.get('APP_DOMAIN','')
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',domain):
        errors.append('Укажите домен без протокола и пути в APP_DOMAIN')
    if domain.endswith(('.test','.localhost','.invalid')) or domain in ('app.example.ru','example.com','example.ru'):
        errors.append('Замените демонстрационный домен настоящим')
    origin=values.get('PUBLIC_ORIGIN','')
    parsed=urlparse(origin)
    if origin!=f'https://{domain}' or parsed.username or parsed.password:
        errors.append('PUBLIC_ORIGIN должен быть https:// плюс APP_DOMAIN, без пути')
    token=values.get('MAX_BOT_TOKEN','')
    if not token or any(ch.isspace() for ch in token):
        errors.append('Заполните MAX_BOT_TOKEN корректным токеном без пробелов')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}',values.get('MAX_WEBHOOK_SECRET','')):
        errors.append('MAX_WEBHOOK_SECRET: нужна случайная строка из 32–256 символов')
    ids=values.get('ADMIN_IDS','')
    if not re.fullmatch(r'[1-9][0-9]*(?:\s*,\s*[1-9][0-9]*)*',ids):
        errors.append('Укажите хотя бы один MAX ID сотрудника УК в ADMIN_IDS')
    if values.get('MINIAPP_ENABLED') not in ('0','1'):
        errors.append('MINIAPP_ENABLED должен быть 0 или 1')
    training=values.get('TRAINING_INCIDENTS_ENABLED','0')
    if training not in ('0','1'):
        errors.append('TRAINING_INCIDENTS_ENABLED должен быть 0 или 1')
    dispatchers=values.get('DISPATCHER_IDS','')
    if training=='1' and not re.fullmatch(r'[1-9][0-9]*(?:\s*,\s*[1-9][0-9]*)*',dispatchers):
        errors.append('Для учебного режима укажите DISPATCHER_IDS отдельно от ADMIN_IDS')
    return errors


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--env',default='.env.pilot')
    args=parser.parse_args()
    path=Path(args.env)
    if not path.exists():
        print('Не найден файл настроек пилота. Подготовьте его по .env.pilot.example; значения секретов не выводятся.')
        return 1
    values={}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key,value=line.split('=',1);values[key.strip()]=value.strip()
    errors=check(values)
    if path.stat().st_mode & 0o077:
        errors.append('Ограничьте права файла настроек: chmod 600 '+str(path))
    if errors:
        print('\n'.join('• '+error for error in errors));return 1
    print('Настройки заполнены. Это не проверка DNS, сертификата, токена или привязки URL в MAX.')
    return 0


if __name__=='__main__':raise SystemExit(main())
