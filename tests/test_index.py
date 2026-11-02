"""The job library (hunt.search.index): migration of an old library.

All data is synthetic; nothing is fetched.
"""
import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hunt.app.store import Store
from hunt.base import Error
from hunt.search import index

LEGACY = Path(__file__).parent / 'fixtures' / 'legacy-064dcda.sql'


def legacy_library(root):
    """A data directory written by the program at 064dcda: jobs(id, identity, data) and no schema_version."""
    root.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(str(root / 'state.sqlite3'))) as c:
        c.executescript(LEGACY.read_text(encoding='utf-8'))
    return root


class LegacyLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = legacy_library(Path(self.tmp.name) / 'app')
        with contextlib.closing(sqlite3.connect(str(self.root / 'state.sqlite3'))) as c:
            self.before = dict(c.execute('SELECT identity, data FROM jobs'))

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        with contextlib.closing(sqlite3.connect(str(self.root / 'state.sqlite3'))) as c:
            c.row_factory = sqlite3.Row
            return {r['identity']: dict(r) for r in c.execute('SELECT * FROM jobs')}

    def test_fixture_is_the_old_format(self):
        with contextlib.closing(sqlite3.connect(str(self.root / 'state.sqlite3'))) as c:
            self.assertEqual([r[1] for r in c.execute('PRAGMA table_info(jobs)')], ['id', 'identity', 'data'])
            self.assertIsNone(c.execute("SELECT 1 FROM meta WHERE key='schema_version'").fetchone())
        self.assertEqual(len(self.before), 5)

    def test_opening_upgrades_columns_and_keeps_the_json(self):
        store = Store(self.root)
        rows = self.rows()
        self.assertEqual({k: r['data'] for k, r in rows.items()}, self.before)
        with store.tx() as c:
            self.assertEqual(store.meta(c, 'schema_version'), index.SCHEMA_VERSION)
        feishu, card, ali, paste = rows['feishu:7300000000000000001'], rows['liepin:LP001'], rows['alibaba:ALI9'], rows['url:https://careers.example.com/jobs/42']
        self.assertEqual((feishu['company'], feishu['title'], feishu['city'], feishu['source'], feishu['source_id'], feishu['platform_id']),
                         ('字节跳动', 'AI产品经理-抖音电商', '深圳', 'feishu', 'feishu:jobs.bytedance.com', '7300000000000000001'))
        self.assertEqual(card['city'], '深圳')  # 深圳市南山区
        self.assertEqual(ali['city'], '杭州/北京')
        self.assertEqual(paste['city'], None)  # 地点未知
        self.assertEqual(feishu['first_seen'], '2026-10-27T04:00:00.000000+00:00')
        self.assertGreater(feishu['last_seen'], feishu['first_seen'])  # the later source_changed event
        self.assertEqual((ali['status'], feishu['status'], card['status']), ('closed', 'open', 'open'))
        self.assertEqual(len(store.state()['jobs']), 5)

    def test_upgrade_runs_once_and_search_reads_old_rows(self):
        Store(self.root)
        store = Store(self.root)
        with store.tx() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs_fts').fetchone()[0], 5)
        with store.tx() as c:
            found = index.search(c, '大模型 MaaS')
        self.assertEqual([g['company'] for g in found['groups']], ['阿里巴巴'])

    def test_old_identities_still_deduplicate(self):
        store = Store(self.root)
        _, duplicate = store.import_job(dict(title='大模型产品专家', jd='负责 MaaS 平台。', company='阿里巴巴', channel='alibaba',
                                             platform_id='ALI9', location='杭州/北京'))
        self.assertTrue(duplicate)
        self.assertEqual(len(self.rows()), 5)

    def test_a_newer_library_is_refused(self):
        Store(self.root)
        with contextlib.closing(sqlite3.connect(str(self.root / 'state.sqlite3'))) as c:
            c.execute("UPDATE meta SET value='99' WHERE key='schema_version'"); c.commit()
        with self.assertRaisesRegex(Error, '更新版本'):
            Store(self.root)


if __name__ == '__main__':
    unittest.main()
