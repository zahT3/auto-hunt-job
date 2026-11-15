import json
import ssl
import unittest
from unittest import mock

from hunt.net import network
from hunt.net.network import FetchError, TransientFetchError
from hunt.search import engine
from hunt.search.engine import discover

URL = 'https://zhaopin.jd.com/web/job/job_info_list/3'


class FakeConn:
    """Stands in for _PinnedHTTPS: request() raises `error`, or answers with `status`."""
    def __init__(self, error=None, status=200):
        self.error, self.status, self.sock = error, status, None
    def request(self, *a, **k):
        if self.error: raise self.error
    def getresponse(self):
        outer = self
        class R:
            status = outer.status
            def getheader(self, name, default=None): return default
            def read(self, n): return b'{}'
        return R()
    def close(self): pass


def fetch_with(conn):
    with mock.patch.object(network, 'resolve_public', return_value=['93.184.216.34']), \
         mock.patch.object(network, '_PinnedHTTPS', lambda *a: conn):
        return network.fetch('https://example.test/x')


class Classification(unittest.TestCase):
    def test_dropped_connection_and_timeout_are_transient(self):
        for error in (ssl.SSLEOFError(8, 'EOF occurred in violation of protocol'), TimeoutError('timed out'), ConnectionResetError()):
            with self.assertRaises(TransientFetchError, msg=repr(error)):
                fetch_with(FakeConn(error))

    def test_status_and_other_errors_are_not(self):
        for conn in (FakeConn(status=404), FakeConn(status=503), FakeConn(error=ssl.SSLCertVerificationError('bad cert'))):
            with self.assertRaises(FetchError) as cm:
                fetch_with(conn)
            self.assertNotIsInstance(cm.exception, TransientFetchError)


class Flaky:
    def __init__(self, failures, error=TransientFetchError('公开抓取失败：timed out')):
        self.failures, self.error, self.calls = failures, error, 0
    def __call__(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.failures: raise self.error
        rows = [dict(id=1, positionName='内部', positionNameOpen='产品经理', workCity='北京', workContent='产品规划', qualification='需求分析')]
        return json.dumps(len(rows) if url.endswith('/job_count') else rows).encode()


def run(transport, **config):
    return discover(dict(dict(keywords=['产品经理'], discovery_sources=[dict(careers_url=URL)], check_entries=False), **config),
                    transport=transport)


class BudgetRetry(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(engine.time, 'sleep'); self.sleep = patch.start(); self.addCleanup(patch.stop)

    def test_one_transient_failure_is_retried_and_counted(self):
        transport = Flaky(1)
        result = run(transport)
        report = result['sources'][0]
        self.assertEqual(report['status'], 'ok'); self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(report['retries'], 1)
        self.assertEqual(report['requests'], transport.calls)  # the retry used a request of the budget
        self.sleep.assert_called_once_with(engine.RETRY_BACKOFF)

    def test_second_failure_is_not_retried_again(self):
        transport = Flaky(2)
        report = run(transport)['sources'][0]
        self.assertEqual((report['status'], report['retries'], transport.calls), ('fetch_error', 1, 2))

    def test_non_transient_errors_are_not_retried(self):
        transport = Flaky(5, FetchError('公开请求 HTTP 500'))
        report = run(transport)['sources'][0]
        self.assertEqual((transport.calls, report['retries']), (1, 0)); self.sleep.assert_not_called()

    def test_no_retry_when_the_budget_is_spent(self):
        transport = Flaky(5)
        report = run(transport, discovery_requests=1)['sources'][0]
        self.assertEqual((transport.calls, report['retries'], report['status']), (1, 0, 'fetch_error'))


if __name__ == '__main__':
    unittest.main()
