"""SQLite online backups. No secrets in output; archives contain private app data."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time


def snapshot(sources, destination):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True,mode=0o700)
    sources=[Path(p).resolve() for p in sources]
    if not sources or len({p.name for p in sources})!=len(sources):
        raise ValueError('Sources must have unique filenames')
    if any(not p.is_file() for p in sources):
        raise ValueError('Database not ready; backup deferred')
    stage=Path(tempfile.mkdtemp(prefix='.pending-',dir=destination))
    try:
        manifest={'format':'domovoy-sqlite-backup-1','created_utc':datetime.now(timezone.utc).isoformat(),'files':[],'cross_database_atomic':False}
        for source in sources:
            target=stage/source.name
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('Backup integrity check failed')
            target.chmod(0o600)
            manifest['files'].append({'name':target.name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        mf=stage/'manifest.json';mf.write_text(json.dumps(manifest,indent=2)+'\n');mf.chmod(0o600)
        name='snapshot-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        final=destination/name;stage.rename(final)
        return final
    finally:
        if stage.exists():shutil.rmtree(stage)


def verify(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    if manifest.get('format')!='domovoy-sqlite-backup-1' or not manifest.get('files'):
        raise ValueError('Unknown backup format')
    for item in manifest['files']:
        name=item['name']
        if Path(name).name!=name:raise ValueError('Invalid backup filename')
        target=folder/name
        if hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Checksum mismatch')
        with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Invalid database')
    return len(manifest['files'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',action='append')
    parser.add_argument('--destination',default='/backups')
    parser.add_argument('--verify')
    parser.add_argument('--loop',action='store_true')
    parser.add_argument('--interval',type=int,default=21600)
    args=parser.parse_args()
    if args.verify:
        print('Verified databases:',verify(args.verify));return
    if args.interval<60:parser.error('interval must be at least 60 seconds')
    sources=args.source or ['/app/data/pilot.sqlite3','/app/data/bot.sqlite3']
    while True:
        try:
            saved=snapshot(sources,args.destination)
            print('Backup ready:',saved.name,flush=True)
        except (ValueError,sqlite3.Error,OSError):
            if not args.loop:raise SystemExit('Backup failed; check database paths and writable destination')
            print('Backup not ready; retry in 60 seconds',flush=True)
            time.sleep(60);continue
        if not args.loop:return
        time.sleep(args.interval)

if __name__=='__main__':main()
