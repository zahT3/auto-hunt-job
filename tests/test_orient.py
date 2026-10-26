"""Orientation: follow-up questions and job directions, with and without a model. The model is always a fake transport."""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from hunt import directions, orient
from hunt.server import periodic
from hunt.core import Error, Store

KEY = 'test-key-0123456789abcd'
PHONE, EMAIL, NAME = '13812345678', 'zhangwei@example.com', '张伟'


def fact(ident, text):
    return dict(id=ident, text=text, source=dict(kind='upload', reference='resume.docx#' + ident), status='confirmed',
                version=1, disclosure='private')


def candidate():
    facts = [fact('f1', '姓名：%s' % NAME), fact('f2', '电话：%s 邮箱：%s' % (PHONE, EMAIL)),
             fact('f3', '工作经历：3 年 Java 后端开发，使用 Python 和 SQL 维护订单服务。'),
             fact('f4', '本科，计算机科学与技术。')]
    facts.append(dict(fact('f5', '未确认的一条'), status='unconfirmed'))
    return dict(name=NAME, synthetic=False, version=2, facts=facts,
                fields=dict(name=dict(value=NAME, fact_ids=['f1'])))


class FakeModel:
    """Queue of replies: dicts become the model's JSON content, an Exception is raised, bytes are returned as-is."""
    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def __call__(self, url, method='GET', data=None, headers=None, bearer=None, timeout=None):
        self.bodies.append(data.decode('utf-8'))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, bytes):
            return reply
        return json.dumps(dict(choices=[dict(message=dict(content=json.dumps(reply, ensure_ascii=False)))],
                               usage=dict(prompt_tokens=2000, completion_tokens=500))).encode()


QUESTIONS = dict(questions=[
    dict(id='q1', text='你更想做后端还是数据？', kind='choice', options=['后端', '数据']),
    dict(id='q2', text='想去哪个城市？', kind='text', options=[]),
    dict(id='q3', text='期望做多久？', kind='text', options=[])])


class OrientCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / 'data')
        with self.store.tx() as c:
            self.store.setmeta(c, 'candidate', candidate())

    def enable_ai(self, kinds=('resume_redacted',)):
        self.store.action(dict(action='ai_settings', api_key=KEY))
        self.store.action(dict(action='ai_consent', kinds=list(kinds)))

    def use(self, *replies):
        self.store.llm_transport = FakeModel(*replies)
        return self.store.llm_transport


class QuestionTests(OrientCase):
    def test_without_consent_nothing_is_sent_and_fixed_questions_are_used(self):
        model = self.use()
        self.store.action(dict(action='ai_settings', api_key=KEY))  # a key alone is not consent
        self.store.action(dict(action='orient_questions'))
        o = self.store.orientation()
        self.assertEqual(model.bodies, [])
        self.assertEqual(o['by'], 'rules')
        self.assertEqual([q['id'] for q in o['questions']], ['family', 'city', 'years', 'remote', 'exclude', 'switch'])
        self.assertEqual(o['questions'][0]['options'], orient.families())
        self.assertTrue(any('同意' in n for n in o['notes']))
        self.assertEqual(o['spent_cny'], 0)

    def test_consent_without_key_sends_nothing(self):
        model = self.use()
        self.store.action(dict(action='ai_consent', kinds=['resume_redacted']))
        self.store.action(dict(action='orient_questions'))
        self.assertEqual(model.bodies, [])
        self.assertEqual(self.store.orientation()['by'], 'rules')

    def test_redacted_facts_only_and_spend_recorded(self):
        self.enable_ai()
        model = self.use(QUESTIONS)
        self.store.action(dict(action='orient_questions'))
        self.assertEqual(len(model.bodies), 1)
        sent = model.bodies[0]
        for secret in (PHONE, EMAIL, NAME, '未确认的一条'):
            self.assertNotIn(secret, sent)
        self.assertIn('Java 后端开发', sent)
        o = self.store.orientation()
        self.assertEqual((o['by'], [q['id'] for q in o['questions']]), ('ai', ['q1', 'q2', 'q3']))
        self.assertAlmostEqual(o['spent_cny'], (2000 * 1 + 500 * 2) / 1e6, places=6)

    def test_full_resume_is_sent_only_when_full_is_consented(self):
        self.enable_ai(['resume_full'])
        model = self.use(QUESTIONS)
        self.store.action(dict(action='orient_questions'))
        self.assertIn(EMAIL, model.bodies[0])
        self.assertNotIn('未确认的一条', model.bodies[0])

    def test_consent_for_another_host_is_void(self):
        self.enable_ai()
        self.store.action(dict(action='ai_settings', base_url='https://api.other.com', api_key=KEY))
        model = self.use()
        self.store.action(dict(action='orient_questions'))
        self.assertEqual((model.bodies, self.store.orientation()['by']), ([], 'rules'))

    def test_too_few_or_malformed_model_questions_fall_back_to_fixed(self):
        self.enable_ai()
        bad = dict(questions=[dict(id='q1', text='ok', kind='text', options=[]), dict(id='bad id!', text='x', kind='text', options=[]),
                              dict(id='q3', text='x', kind='choice', options=['only one']), 'junk'])
        for reply in (bad, dict(other=1), b'not json'):
            self.use(reply)
            self.store.action(dict(action='orient_questions'))
            o = self.store.orientation()
            self.assertEqual(o['by'], 'rules')
            self.assertEqual(len(o['questions']), 6)
            self.assertTrue(o['notes'])

    def test_model_question_ids_cannot_reuse_fixed_ids(self):
        self.enable_ai()
        clash = dict(questions=[dict(id=i, text='问题 ' + i, kind='text', options=[]) for i in ('city', 'years', 'remote', 'exclude', 'q1', 'q2')])
        self.use(clash)
        self.store.action(dict(action='orient_questions'))
        o = self.store.orientation()
        self.assertEqual(o['by'], 'rules')  # only q1 and q2 stay valid: fewer than 3
        self.assertEqual(orient._clean_questions(clash['questions'])[0]['id'], 'q1')

    def test_model_questions_are_capped(self):
        self.enable_ai()
        many = dict(questions=[dict(id='q%d' % i, text='问题%d' % i, kind='text', options=[]) for i in range(10)])
        self.use(many)
        self.store.action(dict(action='orient_questions'))
        self.assertEqual(len(self.store.orientation()['questions']), 6)


class ProposeTests(OrientCase):
    def ask(self):
        self.store.action(dict(action='orient_questions'))

    def test_rules_use_answered_family_and_stay_in_the_table(self):
        self.ask()
        family = directions.get('backend')['family']
        self.store.action(dict(action='orient_answer', answers=dict(family=[family], city='北京、上海', years='3-5 年',
                                                                    remote='接受远程', exclude='游戏，金融', switch='沿用现有经历的方向')))
        o = self.store.orientation()
        ids = [d['id'] for d in o['directions']]
        self.assertTrue(1 <= len(ids) <= 4)
        self.assertTrue(all(i in {r['id'] for r in directions.load()} for i in ids))
        self.assertTrue(all(directions.get(i)['family'] == family for i in ids))
        self.assertEqual({d['source'] for d in o['directions']}, {'rules'})
        self.assertEqual(o['by'], 'rules')
        self.assertEqual(o['conditions'], dict(cities=['北京', '上海'], years='3-5 年', remote=True, exclude_industries=['游戏', '金融']))
        self.assertTrue(2 <= len(o['terms']) <= 8)
        self.assertEqual(o['answers']['city'], '北京、上海')

    def test_rule_directions_cite_confirmed_facts_only(self):
        self.ask()
        self.store.action(dict(action='orient_answer', answers={}))
        ds = self.store.orientation()['directions']
        cited = {f for d in ds for f in d['fact_ids']}
        self.assertTrue(cited and cited <= {'f3', 'f4'})  # never the unconfirmed f5

    def test_no_evidence_and_no_family_gives_no_directions_and_a_note(self):
        with self.store.tx() as c:
            self.store.setmeta(c, 'candidate', dict(candidate(), facts=[fact('f1', '喜欢旅行和读书')]))
        self.ask()
        self.store.action(dict(action='orient_answer', answers={}))
        o = self.store.orientation()
        self.assertEqual((o['directions'], o['terms']), ([], []))
        self.assertTrue(any('请自己选择' in n for n in o['notes']))

    def test_answers_are_validated_against_the_questions(self):
        with self.assertRaisesRegex(Error, '追问'):
            self.store.action(dict(action='orient_answer', answers={}))
        self.ask()
        for bad in (None, dict(nope='x'), dict(remote='随便'), dict(city=5), dict(city='x' * 301), dict(family=['不存在的行业'])):
            with self.assertRaises(Error):
                self.store.action(dict(action='orient_answer', answers=bad))

    def test_model_proposal_drops_unknown_ids_and_foreign_facts_and_records_it(self):
        self.enable_ai()
        self.use(QUESTIONS)
        self.ask()
        proposal = dict(
            directions=[dict(id='backend', why='三年后端经历', fact_ids=['f3', 'f5', 'invented']),
                        dict(id='hack-all', why='ignore previous instructions', fact_ids=['f3']),
                        dict(id='backend', why='重复', fact_ids=[]),
                        dict(id='data-analyst', why='用 SQL', fact_ids=['f3'])],
            conditions=dict(cities=['杭州'], years=3, remote=None, exclude_industries=[]),
            terms=['后端开发', 'Java 工程师', 'mail me at a@b.com', 'x' * 101, 'https://evil.example/x'])
        model = self.use(proposal)
        self.store.action(dict(action='orient_answer', answers=dict(q1='后端', q2='杭州 13900001111')))
        o = self.store.orientation()
        self.assertEqual([d['id'] for d in o['directions']], ['backend', 'data-analyst'])
        self.assertEqual(o['directions'][0]['fact_ids'], ['f3'])
        self.assertEqual({d['source'] for d in o['directions']}, {'ai'})
        self.assertEqual(o['by'], 'ai')
        self.assertEqual(o['terms'], ['后端开发', 'Java 工程师'])
        self.assertEqual(o['conditions']['cities'], ['杭州'])
        self.assertEqual(o['conditions']['years'], '3 年')
        self.assertTrue(any('hack-all' in n for n in o['notes']))
        self.assertTrue(any('未发送的事实' in n for n in o['notes']))
        sent = model.bodies[0]
        self.assertNotIn('13900001111', sent)  # typed answers are redacted like the facts
        self.assertNotIn(EMAIL, sent)
        self.assertIn('杭州', sent)

    def test_model_terms_without_strings_are_topped_up_not_defaulted(self):
        self.enable_ai()
        self.use(QUESTIONS)
        self.ask()
        for terms in ([1, 2], [None, ['a']], []):
            self.use(dict(directions=[dict(id='backend', why='x', fact_ids=[])], terms=terms))
            self.store.action(dict(action='orient_answer', answers={}))
            o = self.store.orientation()
            self.assertEqual(o['by'], 'ai')
            self.assertTrue(len(o['terms']) >= 2)
            self.assertFalse({'AI', 'Agent', 'Web3'} & set(o['terms']))
            self.assertTrue(any('搜索词不足' in n for n in o['notes']))

    def test_model_may_not_pick_more_than_four_and_must_pick_one(self):
        self.enable_ai()
        self.use(QUESTIONS)
        self.ask()
        ids = [r['id'] for r in directions.load()[:7]]
        self.use(dict(directions=[dict(id=i, why='x', fact_ids=[]) for i in ids], terms=['a', 'b']))
        self.store.action(dict(action='orient_answer', answers={}))
        self.assertEqual(len(self.store.orientation()['directions']), 4)
        self.use(dict(directions=[dict(id='nope', why='x', fact_ids=[])], terms=['a', 'b']))
        self.store.action(dict(action='orient_answer', answers={}))
        o = self.store.orientation()
        self.assertEqual(o['by'], 'rules')
        self.assertTrue(any('nope' in n for n in o['notes']))

    def test_model_failures_fall_back_to_rules_without_failing(self):
        from hunt import network
        self.enable_ai()
        self.use(QUESTIONS)
        self.ask()
        for reply in (b'not json', dict(directions='x'), network.FetchError('boom ' + KEY)):
            self.use(reply)
            self.store.action(dict(action='orient_answer', answers=dict(q1='后端')))
            o = self.store.orientation()
            self.assertEqual(o['by'], 'rules')
            self.assertTrue(o['directions'])
            self.assertNotIn(KEY, json.dumps(o, ensure_ascii=False))

    def test_spend_accumulates_and_budget_stops_the_model(self):
        self.enable_ai()
        self.use(QUESTIONS)
        self.ask()
        one = self.store.orientation()['spent_cny']
        self.use(dict(directions=[dict(id='backend', why='x', fact_ids=[])], terms=['后端开发', 'Java 工程师']))
        self.store.action(dict(action='orient_answer', answers={}))
        self.assertGreater(self.store.orientation()['spent_cny'], one)
        self.store.action(dict(action='ai_settings', budget_cny=0))
        model = self.use()
        self.store.action(dict(action='orient_answer', answers={}))
        self.assertEqual(model.bodies, [])
        self.assertEqual(self.store.orientation()['by'], 'rules')


class DirectionsSetTests(OrientCase):
    def set(self, **payload):
        return self.store.action(dict(action='directions_set', **payload))

    def test_valid_set_is_stored_with_source(self):
        self.set(directions=['backend', dict(id='data-analyst', why='想转数据')], terms=['后端开发', '数据分析师'],
                 conditions=dict(cities=['深圳'], remote=True))
        o = self.store.orientation()
        self.assertEqual([(d['id'], d['source']) for d in o['directions']], [('backend', 'user'), ('data-analyst', 'user')])
        self.assertEqual(o['directions'][1]['why'], '想转数据')
        self.assertEqual((o['by'], o['terms']), ('user', ['后端开发', '数据分析师']))
        self.assertEqual(o['conditions'], dict(cities=['深圳'], years=None, remote=True, exclude_industries=[]))
        self.set(directions=['backend'], source='agent')
        o = self.store.orientation()
        self.assertEqual((o['by'], o['directions'][0]['source']), ('agent', 'agent'))
        self.assertEqual(o['conditions']['cities'], ['深圳'])  # untouched when not given
        self.assertTrue(2 <= len(o['terms']) <= 8)  # derived from the table when not given

    def test_validation(self):
        ok = ['backend']
        bad = [dict(directions=[]), dict(directions='backend'), dict(), dict(directions=['not-in-table']),
               dict(directions=['backend', 'backend']), dict(directions=[r['id'] for r in directions.load()[:5]]),
               dict(directions=[dict(id='backend', why='x' * 201)]), dict(directions=[5]),
               dict(directions=ok, terms=['t%d' % i for i in range(9)]), dict(directions=ok, terms=[]),
               dict(directions=ok, terms=['联系 a@b.com']), dict(directions=ok, terms=['x' * 101]), dict(directions=ok, terms=[1]),
               dict(directions=ok, conditions='x'), dict(directions=ok, conditions=dict(cities='北京')),
               dict(directions=ok, conditions=dict(remote='yes')), dict(directions=ok, conditions=dict(cities=['x' * 31])),
               dict(directions=ok, source='ai')]
        for payload in bad:
            with self.assertRaises(Error, msg=str(payload)):
                self.set(**payload)
        self.assertIsNone(self.store.orientation())


class RunTests(OrientCase):
    def search(self, **config):
        calls = []

        def fake_discover(cfg, **kw):
            calls.append(cfg)
            return dict(jobs=[], sources=[])
        with patch('hunt.discovery.discover', fake_discover):
            run = self.store.run()
        return run, calls

    def test_no_keywords_and_no_directions_is_a_chinese_error(self):
        with self.assertRaisesRegex(Error, '请先确定方向或填写关键词'):
            self.store.run()
        self.assertFalse(self.store.run_lock.locked())
        with self.assertRaisesRegex(Error, '请先确定方向或填写关键词'):
            self.store.start_run()

    def test_orientation_terms_are_used_when_no_keywords_given(self):
        self.store.action(dict(action='directions_set', directions=['backend'], terms=['后端开发', 'Java 工程师']))
        run, calls = self.search()
        self.assertEqual(calls[0]['keywords'], ['后端开发', 'Java 工程师'])
        self.assertEqual(run['status'], 'empty')

    def test_explicit_keywords_win_over_orientation(self):
        self.store.action(dict(action='directions_set', directions=['backend'], terms=['后端开发', 'Java 工程师']))
        cfg = self.store.state()['config']
        self.store.action(dict(action='config', config=dict(cfg, keywords=['产品经理'])))
        _, calls = self.search()
        self.assertEqual(calls[0]['keywords'], ['产品经理'])

    def test_search_config_is_computed_once_per_run(self):
        self.store.action(dict(action='directions_set', directions=['backend'], terms=['后端开发', 'Java 工程师']))
        real, calls = self.store.search_config, []
        self.store.search_config = lambda: calls.append(1) or real()
        self.search()
        self.assertEqual(len(calls), 1)

    def test_periodic_survives_a_missing_direction(self):
        with self.store.tx() as c:
            self.store.setmeta(c, 'config', dict(self.store.meta(c, 'config'), interval_minutes=0.0003))
        stop, calls = threading.Event(), []
        # The real run() raises Error here: a fresh store has neither keywords nor a direction.
        real = self.store.run
        self.store.run = lambda *a, **k: calls.append(1) or real(*a, **k)
        thread = threading.Thread(target=periodic, args=(self.store, stop), daemon=True)
        thread.start()
        deadline = time.time() + 5
        while len(calls) < 2 and time.time() < deadline:
            time.sleep(0.02)
        alive = thread.is_alive()
        stop.set()
        thread.join(2)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(alive)

    def test_once_prints_the_chinese_error_and_exits_nonzero(self):
        root = Path(__file__).resolve().parent.parent
        done = subprocess.run([sys.executable, str(root / 'run.py'), '--once', '--data', str(self.store.root)],
                              capture_output=True, text=True, timeout=60)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('请先确定方向或填写关键词', done.stderr)
        self.assertNotIn('Traceback', done.stderr)

    def test_orientation_without_terms_still_errors(self):
        with self.store.tx() as c:
            self.store.setmeta(c, 'orientation', dict(questions=[], answers={}, directions=[], conditions={}, terms=[], by='rules'))
        with self.assertRaises(Error):
            self.store.run()



class TermsTests(unittest.TestCase):
    def test_slash_names_are_not_search_terms_and_every_term_can_match(self):
        from hunt import directions, discovery
        ids = [r['id'] for r in directions.load()]
        for n in range(0, len(ids), 4):
            terms = orient.terms_for(ids[n:n + 4])
            self.assertTrue(terms)
            self.assertFalse([t for t in terms if '/' in t], ids[n:n + 4])
        self.assertTrue(discovery.matches('总账会计', orient.terms_for(['accountant'])))


if __name__ == '__main__':
    unittest.main()
