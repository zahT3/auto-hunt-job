import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hunt import llm, network
from hunt.__main__ import main
from hunt.core import Error, Store

KEY = 'test-key-0123456789abcd'


def fake_https(status=200, body=b'{}', location=None):
    """Patch DNS and the pinned connection; returns the list of (host, ip, request headers) seen."""
    seen = []

    class Response:
        def __init__(self): self.status = status
        def getheader(self, name, default=None):
            return location if name == 'Location' else default
        def read(self, n=-1): return body

    class Conn:
        sock = None
        def __init__(self, host, ip, timeout): self.host, self.ip, self.timeout = host, ip, timeout
        def request(self, method, path, body=None, headers=None): seen.append((self.host, self.ip, dict(headers or {})))
        def getresponse(self): return Response()
        def close(self): pass

    return seen, patch.object(network, 'resolve_public', return_value=['8.8.8.8']), patch.object(network, '_PinnedHTTPS', Conn)


class BearerTests(unittest.TestCase):
    def test_bearer_format_and_no_redirect(self):
        for bad in ('short', 'a' * 513, 'has space 12345', 'x\r\nHost: evil1', 'tok/en=12345678', ''):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                network.fetch('https://api.example.com/v1', bearer=bad)
        # GET too: plain fetch() would follow this redirect, so it is the bearer guard that must stop it.
        for method, data in (('GET', None), ('POST', b'{}')):
            for status in (301, 302, 303, 307, 308):
                with self.subTest(method=method, status=status):
                    seen, dns, conn = fake_https(status=status, location='https://other.example.org/steal')
                    with dns, conn, self.assertRaises(network.FetchError):
                        network.fetch('https://api.example.com/v1', method=method, data=data, bearer=KEY)
                    self.assertEqual([h for h, _, _ in seen], ['api.example.com'])
                    self.assertEqual(seen[0][2]['Authorization'], 'Bearer ' + KEY)

    def test_without_bearer_no_authorization_and_redirects_still_followed(self):
        seen, dns, conn = fake_https(status=200, body=b'ok')
        with dns, conn:
            self.assertEqual(network.fetch('https://api.example.com/'), b'ok')
        self.assertNotIn('Authorization', seen[0][2])

    def test_headers_authorization_still_refused(self):
        for name in ('Authorization', 'authorization', 'Proxy-Authorization'):
            with self.subTest(name=name), self.assertRaises(network.FetchError):
                network.fetch('https://api.example.com/', headers={name: 'Bearer ' + KEY})
            with self.subTest(name=name, with_bearer=True), self.assertRaises(network.FetchError):
                network.fetch('https://api.example.com/', headers={name: 'Bearer other-key-12345'}, bearer=KEY)

    def test_header_name_whitespace_and_control_refused(self):
        for name in ('Authorization ', ' Authorization', 'Authorization\t', 'Cookie ', 'Host\x00', 'X Y', 'X:Y', ''):
            with self.subTest(name=name), self.assertRaises(network.FetchError):
                network.fetch('https://api.example.com/', headers={name: 'Bearer other-key-12345'})
        seen, dns, conn = fake_https(body=b'ok')
        with dns, conn:
            network.fetch('https://api.example.com/', headers={'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json'})
        self.assertEqual(seen[0][2]['X-Requested-With'], 'XMLHttpRequest')

    def test_timeout_is_clamped(self):
        seen = []
        class Conn:
            sock = None
            def __init__(self, host, ip, timeout): seen.append(timeout)
            def request(self, *a, **k): pass
            def getresponse(self):
                class R:
                    status = 200
                    def getheader(self, n, d=None): return d
                    def read(self, n=-1): return b'x'
                return R()
            def close(self): pass
        with patch.object(network, 'resolve_public', return_value=['8.8.8.8']), patch.object(network, '_PinnedHTTPS', Conn):
            network.fetch('https://api.example.com/', timeout=500)
            network.fetch('https://api.example.com/', timeout=0)
            network.fetch('https://api.example.com/')
        self.assertTrue(120 < seen[0] <= 180)
        self.assertTrue(.5 < seen[1] <= 1)
        self.assertTrue(20 < seen[2] <= 25)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_defaults_and_validation(self):
        self.assertEqual(llm.load_settings(self.root), dict(base_url='https://api.deepseek.com', model='deepseek-v4-flash',
                                                              price_in=1, price_out=2, budget_cny=5))
        for bad in (dict(base_url='http://api.deepseek.com'), dict(base_url='https://localhost'), dict(base_url='https://u:p@example.com'),
                    dict(base_url='https://example.com/?a=1'), dict(model='a b'), dict(model=''), dict(budget_cny=101),
                    dict(budget_cny=-1), dict(price_in='x'), dict(price_out=float('inf')), dict(budget_cny=True)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                llm.save_settings(self.root, bad)
        saved = llm.save_settings(self.root, dict(base_url='https://example.com/v1/', model='m-1', budget_cny=0))
        self.assertEqual(saved['base_url'], 'https://example.com/v1')
        self.assertEqual(llm.load_settings(self.root), saved)
        self.assertEqual(llm.host(saved), 'example.com')

    def test_temp_file_removed_when_replace_fails(self):
        with patch('os.replace', side_effect=OSError('disk')), self.assertRaises(OSError):
            llm.save_key(self.root, KEY, 'api.deepseek.com')
        self.assertEqual(list(self.root.iterdir()), [])
        with patch('os.chmod', side_effect=OSError('perm')), self.assertRaises(OSError):
            llm.save_settings(self.root, {})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_key_file_permissions_and_hint(self):
        self.assertIsNone(llm.key_hint(self.root))
        with self.assertRaises(ValueError):
            llm.save_key(self.root, 'bad key', 'api.deepseek.com')
        llm.save_key(self.root, KEY, 'api.deepseek.com')
        path = self.root / 'secrets.json'
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(llm.key_hint(self.root), KEY[-4:])
        self.assertEqual(llm.load_key(self.root, 'api.deepseek.com'), KEY)
        llm.save_key(self.root, KEY[::-1], 'api.deepseek.com')  # overwrite keeps the mode
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual([p.name for p in self.root.iterdir()], ['secrets.json'])
        store = Store(self.root)
        self.assertNotIn(KEY, json.dumps(store.state()))
        self.assertNotIn(KEY[::-1], json.dumps(store.state()))
        self.assertEqual(store.state()['ai']['key_hint'], KEY[::-1][-4:])


class KeyHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_key_bound_to_host(self):
        llm.save_key(self.root, KEY, 'api.deepseek.com')
        self.assertEqual(llm.load_key(self.root, 'api.deepseek.com'), KEY)
        self.assertIsNone(llm.load_key(self.root, 'api.other.com'))
        self.assertEqual(llm.key_host(self.root), 'api.deepseek.com')
        (self.root / 'secrets.json').write_text(json.dumps(dict(api_key=KEY)))  # legacy file without host
        self.assertIsNone(llm.load_key(self.root, 'api.deepseek.com'))

    def test_changing_base_url_stops_old_key(self):
        store = Store(self.root / 'data')
        store.action(dict(action='ai_settings', api_key=KEY))
        ai = store.state()['ai']
        self.assertEqual((ai['key_hint'], ai['key_host'], ai['key_mismatch']), (KEY[-4:], 'api.deepseek.com', False))
        ai = store.action(dict(action='ai_settings', base_url='https://api.other.com'))['ai']
        self.assertEqual((ai['key_hint'], ai['key_host'], ai['key_mismatch'], ai['active']), (None, 'api.deepseek.com', True, False))
        settings = ai['settings']
        key = llm.load_key(store.root, llm.host(settings))
        self.assertIsNone(key)
        calls = []
        with self.assertRaises(llm.LLMError) as cm:
            llm.chat_json(settings, key, [dict(role='user', content='x')], ['a'], llm.Meter(5, 1, 2),
                          transport=lambda *a, **k: calls.append(1))
        self.assertEqual(cm.exception.code, 'no_key')
        self.assertIn('重新输入', cm.exception.message)
        self.assertEqual(calls, [])
        # Entering a key with the new settings binds it to the new host.
        ai = store.action(dict(action='ai_settings', api_key=KEY))['ai']
        self.assertEqual((ai['key_host'], ai['key_mismatch'], ai['key_hint']), ('api.other.com', False, KEY[-4:]))


class ConsentTests(unittest.TestCase):
    def test_consent_bound_to_host_and_model(self):
        settings = dict(llm.DEFAULTS)
        consent = dict(host='api.deepseek.com', model='deepseek-v4-flash', kinds=['resume_redacted'], granted_at='t')
        self.assertTrue(llm.consent_ok(consent, settings, 'resume_redacted'))
        self.assertFalse(llm.consent_ok(consent, settings, 'resume_full'))
        self.assertFalse(llm.consent_ok(consent, settings, 'job_text'))
        self.assertFalse(llm.consent_ok(consent, dict(settings, model='other-model'), 'resume_redacted'))
        self.assertFalse(llm.consent_ok(consent, dict(settings, base_url='https://api.other.com'), 'resume_redacted'))
        self.assertFalse(llm.consent_ok(None, settings, 'resume_redacted'))
        self.assertFalse(llm.consent_ok(dict(host='api.deepseek.com', model='deepseek-v4-flash'), settings, 'resume_redacted'))


class MeterTests(unittest.TestCase):
    def test_meter_caps_and_estimates(self):
        meter = llm.Meter(budget_cny=1, price_in=1, price_out=2)
        self.assertFalse(meter.exhausted)
        meter.charge(400_000, 200_000)  # 0.4 + 0.4
        self.assertAlmostEqual(meter.spent, .8)
        self.assertFalse(meter.exhausted or meter.estimated)
        meter.estimate(prompt_chars=150_000, completion_chars=0)  # 100k tokens in -> +0.1
        self.assertTrue(meter.estimated)
        self.assertAlmostEqual(meter.spent, .9)
        meter.charge(100_000, 0)
        self.assertTrue(meter.exhausted)
        self.assertTrue(llm.Meter(0, 1, 2).exhausted)  # budget 0 means no model calls at all


def reply(content, usage=None):
    body = dict(choices=[dict(message=dict(role='assistant', content=content))])
    if usage: body['usage'] = usage
    return json.dumps(body).encode()


class ChatTests(unittest.TestCase):
    messages = [dict(role='system', content='json only'), dict(role='user', content='分类')]

    def call(self, raw, meter=None, keys=('a',)):
        calls = []
        def transport(url, **kw):
            calls.append((url, kw))
            if isinstance(raw, Exception): raise raw
            return raw
        meter = meter or llm.Meter(5, 1, 2)
        try:
            return llm.chat_json(dict(llm.DEFAULTS), KEY, self.messages, list(keys), meter, transport=transport), calls, meter
        except llm.LLMError as e:
            e.calls, e.meter = calls, meter
            raise

    def test_success_request_shape_and_usage_charge(self):
        result, calls, meter = self.call(reply('{"a": 1}', dict(prompt_tokens=1000, completion_tokens=500)))
        self.assertEqual(result, dict(a=1))
        url, kw = calls[0]
        self.assertEqual(url, 'https://api.deepseek.com/chat/completions')
        self.assertEqual((kw['method'], kw['bearer'], kw['timeout']), ('POST', KEY, 120))
        body = json.loads(kw['data'])
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertEqual(body['model'], 'deepseek-v4-flash')
        self.assertFalse('Authorization' in kw['headers'])
        self.assertAlmostEqual(meter.spent, (1000 * 1 + 500 * 2) / 1e6)
        self.assertFalse(meter.estimated)

    def test_reasoning_allowance_is_added_and_counted_in_the_worst_case(self):
        result, calls, meter = self.call(reply('{"a": 1}'))
        self.assertEqual(json.loads(calls[0][1]['data'])['max_tokens'], 2000 + llm.REASONING_ALLOWANCE)
        # Worst case of one call must include the allowance, so a tight budget refuses before sending.
        tight = llm.Meter(((2000 + llm.REASONING_ALLOWANCE) * 2 - 1) / 1e6, 1, 2)
        with self.assertRaises(llm.LLMError) as caught:
            self.call(reply('{"a": 1}'), meter=tight)
        self.assertEqual((caught.exception.code, caught.exception.calls), ('budget', []))

    def test_cut_off_answer_says_so(self):
        raw = json.dumps(dict(choices=[dict(message=dict(content='{"a": [1, 2'), finish_reason='length')],
                              usage=dict(prompt_tokens=10, completion_tokens=6000))).encode()
        with self.assertRaises(llm.LLMError) as caught:
            self.call(raw)
        self.assertEqual(caught.exception.code, 'bad_output')
        self.assertIn('截断', caught.exception.message)
        self.assertGreater(caught.exception.meter.spent, 0)  # the tokens were still billed

    def test_chat_json_validates_output(self):
        for content in ('not json', '[1]', '{"b": 1}', '"text"'):
            with self.subTest(content=content), self.assertRaises(llm.LLMError) as cm:
                self.call(reply(content))
            self.assertEqual(cm.exception.code, 'bad_output')
        for raw in (b'<html>', b'{}', b'{"choices": []}', reply(None)):
            with self.subTest(raw=raw), self.assertRaises(llm.LLMError) as cm:
                self.call(raw)
            self.assertEqual(cm.exception.code, 'bad_output')
        meter = llm.Meter(0, 1, 2)
        with self.assertRaises(llm.LLMError) as cm:
            self.call(reply('{"a": 1}'), meter=meter)
        self.assertEqual(cm.exception.code, 'budget')
        self.assertEqual(cm.exception.calls, [])  # no request when the budget is spent

    def test_max_tokens_sent_and_projected_cost_blocks_request(self):
        _, calls, _ = self.call(reply('{"a": 1}', dict(prompt_tokens=1, completion_tokens=1)))
        self.assertEqual(json.loads(calls[0][1]['data'])['max_tokens'], 2000 + llm.REASONING_ALLOWANCE)
        # (2000 + allowance) completion tokens at 2 CNY/M = 0.012 > 0.011 left: refuse before any request.
        with self.assertRaises(llm.LLMError) as cm:
            self.call(reply('{"a": 1}'), meter=llm.Meter(0.011, 1, 2))
        self.assertEqual((cm.exception.code, cm.exception.calls), ('budget', []))
        # Same budget, smaller max_tokens fits.
        calls = []
        llm.chat_json(dict(llm.DEFAULTS), KEY, self.messages, ['a'], llm.Meter(0.011, 1, 2),
                      transport=lambda url, **kw: calls.append(kw) or reply('{"a": 1}'), max_tokens=500)
        self.assertEqual(json.loads(calls[0]['data'])['max_tokens'], 500 + llm.REASONING_ALLOWANCE)
        # Raised prices: one call alone would exceed the whole budget.
        with self.assertRaises(llm.LLMError) as cm:
            self.call(reply('{"a": 1}'), meter=llm.Meter(1, 1000, 1000))
        self.assertEqual((cm.exception.code, cm.exception.calls), ('budget', []))
        # Already-spent amount counts toward the projection.
        meter = llm.Meter(1, 1, 2); meter.charge(997_000, 0)
        with self.assertRaises(llm.LLMError) as cm:
            self.call(reply('{"a": 1}'), meter=meter, )
        self.assertEqual(cm.exception.code, 'budget')

    def test_missing_usage_is_estimated(self):
        _, _, meter = self.call(reply('{"a": "xxxxxxxxxxxxxxx"}'))
        self.assertTrue(meter.estimated)
        self.assertGreater(meter.spent, 0)

    def test_fetch_failure_maps_and_never_leaks_key(self):
        for exc in (network.FetchError('公开请求 HTTP 401 ' + KEY), OSError('boom ' + KEY), ValueError('bearer')):
            with self.subTest(exc=exc), self.assertRaises(llm.LLMError) as cm:
                self.call(exc)
            self.assertEqual(cm.exception.code, 'fetch_error')
            self.assertNotIn(KEY, cm.exception.message)

    def test_bad_output_still_charges_reported_usage(self):
        meter = llm.Meter(5, 1, 2)
        with self.assertRaises(llm.LLMError):
            self.call(reply('nope', dict(prompt_tokens=10, completion_tokens=5)), meter=meter)
        self.assertEqual((meter.prompt_tokens, meter.completion_tokens), (10, 5))


class StoreAIActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'data')

    def test_actions_save_settings_and_consent(self):
        state = self.store.state()
        self.assertFalse(state['ai']['active'])
        self.assertIsNone(state['ai']['consent'])
        self.assertEqual(state['ai']['settings']['model'], 'deepseek-v4-flash')
        state = self.store.action(dict(action='ai_settings', model='m-2', budget_cny=3, api_key=KEY))
        ai = state['ai']
        self.assertEqual((ai['settings']['model'], ai['settings']['budget_cny'], ai['key_hint']), ('m-2', 3, KEY[-4:]))
        self.assertEqual(llm.load_key(self.store.root, 'api.deepseek.com'), KEY)
        with self.store.tx() as c:
            meta = json.dumps([tuple(r) for r in c.execute('SELECT * FROM meta')])
            log = json.dumps([tuple(r) for r in c.execute('SELECT * FROM interventions')])
        self.assertNotIn(KEY, meta + log + json.dumps(state))
        # Omitting api_key keeps the saved key.
        self.store.action(dict(action='ai_settings', budget_cny=4))
        self.assertEqual(llm.load_key(self.store.root, 'api.deepseek.com'), KEY)
        for bad in (dict(kinds=[]), dict(kinds=['everything']), dict(kinds='resume_full'), dict(kinds=['job_text'], model='old-model')):
            with self.subTest(bad=bad), self.assertRaises(Error):
                self.store.action(dict(action='ai_consent', **bad))
        state = self.store.action(dict(action='ai_consent', kinds=['resume_redacted', 'job_text'], host='api.deepseek.com', model='m-2'))
        consent = state['ai']['consent']
        self.assertEqual((consent['host'], consent['model'], consent['kinds']), ('api.deepseek.com', 'm-2', ['resume_redacted', 'job_text']))
        self.assertTrue(consent['granted_at'])
        self.assertTrue(state['ai']['active'])
        # Changing the model voids the stored consent without deleting it.
        state = self.store.action(dict(action='ai_settings', model='m-3'))
        self.assertFalse(state['ai']['consent_current'])
        self.assertFalse(state['ai']['active'])
        state = self.store.action(dict(action='ai_revoke'))
        self.assertIsNone(state['ai']['consent'])

    def test_write_failures_become_error_without_paths_or_key(self):
        for target in ('save_key', 'save_settings'):
            with self.subTest(target=target), patch.object(llm, target, side_effect=OSError('/secret/path ' + KEY)):
                with self.assertRaises(Error) as cm:
                    self.store.action(dict(action='ai_settings', model='m-9', api_key=KEY))
                self.assertNotIn(KEY, str(cm.exception))
                self.assertNotIn('/secret/path', str(cm.exception))
        # Settings are written before the key, so a failing key write never leaves a key bound to stale settings.
        order = []
        real_settings, real_key = llm.save_settings, llm.save_key
        with patch.object(llm, 'save_settings', side_effect=lambda *a: order.append('settings') or real_settings(*a)), \
             patch.object(llm, 'save_key', side_effect=lambda *a: order.append('key') or real_key(*a)):
            self.store.action(dict(action='ai_settings', api_key=KEY))
        self.assertEqual(order, ['settings', 'key'])

    def test_invalid_settings_change_nothing(self):
        self.store.action(dict(action='ai_settings', api_key=KEY))
        with self.assertRaises(Error) as cm:
            self.store.action(dict(action='ai_settings', base_url='http://insecure.example.com', api_key='another-key-1234567'))
        self.assertNotIn('another-key', str(cm.exception))
        self.assertEqual(llm.load_key(self.store.root, 'api.deepseek.com'), KEY)
        with self.assertRaises(Error):
            self.store.action(dict(action='ai_settings', api_key='bad key'))
        with self.assertRaises(Error):
            self.store.action(dict(action='ai_settings', budget_cny=500))
        self.assertEqual(self.store.state()['ai']['settings']['budget_cny'], 5)


class AICLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'data'

    def invoke(self, arguments, stdin=''):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch('sys.stdin', io.StringIO(stdin)):
            code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_key_from_stdin_and_show(self):
        code, out, err = self.invoke(['ai', 'key', '--data', str(self.data)], KEY + '\n')
        self.assertEqual(code, 0, err)
        self.assertIn(KEY[-4:], out)
        self.assertNotIn(KEY, out + err)
        self.assertEqual(stat.S_IMODE(os.stat(self.data / 'secrets.json').st_mode), 0o600)
        code, out, err = self.invoke(['ai', 'show', '--data', str(self.data)])
        self.assertEqual(code, 0, err)
        shown = json.loads(out)
        self.assertNotIn(KEY, out)
        self.assertEqual(shown['key_hint'], KEY[-4:])
        self.assertEqual(shown['settings']['base_url'], 'https://api.deepseek.com')
        self.assertIsNone(shown['consent'])
        self.assertEqual(shown['key_host'], 'api.deepseek.com')
        self.assertIn('未使用 AI', shown['status'])

    def test_cli_key_binds_to_current_settings_host(self):
        Store(self.data).action(dict(action='ai_settings', base_url='https://api.other.com'))
        self.assertEqual(self.invoke(['ai', 'key', '--data', str(self.data)], KEY + '\n')[0], 0)
        self.assertEqual(llm.key_host(self.data), 'api.other.com')
        self.assertEqual(llm.load_key(self.data, 'api.other.com'), KEY)

    def test_getpass_used_on_a_terminal(self):
        class TTY(io.StringIO):
            def isatty(self): return True
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch('sys.stdin', TTY()), patch('getpass.getpass', return_value=KEY) as gp:
            self.assertEqual(main(['ai', 'key', '--data', str(self.data)]), 0)
        gp.assert_called_once()
        self.assertEqual(llm.load_key(self.data, 'api.deepseek.com'), KEY)

    def tty(self, arguments, typed):
        class TTY(io.StringIO):
            def isatty(self): return True
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch('sys.stdin', TTY(typed)):
            code = main(arguments)
        return code, out.getvalue(), err.getvalue()

    def consent(self):
        return Store(self.data).ai_settings()['consent']

    def test_consent_shows_host_and_model_and_needs_yes(self):
        code, out, err = self.tty(['ai', 'consent', '--kind', 'resume_redacted', '--kind', 'job_text', '--data', str(self.data)], 'no\n')
        self.assertEqual(code, 1)
        self.assertIn('api.deepseek.com', out)
        self.assertIn('deepseek-v4-flash', out)
        self.assertIn('脱敏简历', out)
        self.assertIn('岗位原文', out)
        self.assertIn('还没有保存', out)  # no key yet for this host
        self.assertIsNone(self.consent())
        code, out, err = self.tty(['ai', 'consent', '--kind', 'resume_redacted', '--kind', 'job_text', '--data', str(self.data)], 'yes\n')
        self.assertEqual(code, 0, err)
        consent = self.consent()
        self.assertEqual((consent['host'], consent['model'], consent['kinds']), ('api.deepseek.com', 'deepseek-v4-flash', ['resume_redacted', 'job_text']))

    def test_consent_asks_for_kinds_on_a_terminal_and_warns_about_the_full_resume(self):
        code, out, err = self.tty(['ai', 'consent', '--data', str(self.data)], '2,3\nyes\n')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.consent()['kinds'], ['resume_full', 'job_text'])
        self.assertIn('完整简历', out)
        self.assertIn('不脱敏', out)

    def test_consent_without_a_terminal_needs_kinds_and_yes(self):
        code, out, err = self.invoke(['ai', 'consent', '--kind', 'job_text', '--data', str(self.data)])
        self.assertEqual(code, 1)
        self.assertIn('--yes', err)
        self.assertIsNone(self.consent())
        code, out, err = self.invoke(['ai', 'consent', '--yes', '--data', str(self.data)])
        self.assertEqual(code, 1)
        self.assertIn('--kind', err)
        code, out, err = self.invoke(['ai', 'consent', '--kind', 'job_text', '--yes', '--data', str(self.data)])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.consent()['kinds'], ['job_text'])

    def test_bad_kind_number_is_rejected(self):
        code, out, err = self.tty(['ai', 'consent', '--data', str(self.data)], '9\n')
        self.assertEqual(code, 1)
        self.assertIsNone(self.consent())

    def test_revoke_clears_consent(self):
        self.invoke(['ai', 'consent', '--kind', 'job_text', '--yes', '--data', str(self.data)])
        code, out, err = self.invoke(['ai', 'revoke', '--data', str(self.data)])
        self.assertEqual(code, 0, err)
        self.assertIn('已撤销', out)
        self.assertIsNone(self.consent())

    def test_bad_key_is_rejected_without_echo(self):
        code, out, err = self.invoke(['ai', 'key', '--data', str(self.data)], 'bad key with spaces\n')
        self.assertEqual(code, 1)
        self.assertNotIn('bad key with spaces', out + err)
        self.assertIsNone(llm.key_hint(self.data))


if __name__ == '__main__':
    unittest.main()
