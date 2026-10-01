import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
import backup

class BackupTests(unittest.TestCase):
    def test_wal_snapshot_restores_committed_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'shared.db'
            with closing(sqlite3.connect(source)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY,text TEXT)')
                db.execute('INSERT INTO entries(text) VALUES(?)',('Учебные данные',));db.commit()
                saved=backup.snapshot([source],root/'snapshots')
                db.execute('DELETE FROM entries');db.commit()
            self.assertEqual(backup.verify(saved),1)
            with closing(sqlite3.connect(saved/'shared.db')) as restored:
                self.assertEqual(restored.execute('SELECT text FROM entries').fetchone()[0],'Учебные данные')
            self.assertEqual((saved/'shared.db').stat().st_mode & 0o777,0o600)
    def test_missing_database_does_not_publish_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(ValueError):backup.snapshot([root/'missing.db'],root/'snapshots')
            self.assertEqual(list((root/'snapshots').iterdir()),[])
    def test_corrupt_copy_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'data.db'
            with closing(sqlite3.connect(source)) as db:db.execute('CREATE TABLE entries(id INTEGER)');db.commit()
            saved=backup.snapshot([source],root/'snapshots')
            with (saved/'data.db').open('ab') as f:f.write(b'corruption')
            with self.assertRaises(ValueError):backup.verify(saved)
