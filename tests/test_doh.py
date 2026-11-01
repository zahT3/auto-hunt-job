"""Public DNS-over-HTTPS fallback: Cloudflare first, then AliDNS, then Tencent DNSPod; only the hostname is sent."""
import json
import ssl
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from hunt.net import network


def answer(*ips, status=0):
    return json.dumps(dict(Status=status, Answer=[dict(type=1, data=ip) for ip in ips])).encode()


class FakeConnection:
    """Stands in for _PinnedHTTPS. `plan` maps an endpoint IP to an exception, an HTTP status, or a JSON body."""
    calls = []
    plan = {}

    def __init__(self, hostname, ip, timeout):
        self.hostname, self.ip, self.timeout = hostname, ip, timeout

    def request(self, method, url, headers=None):
        FakeConnection.calls.append(dict(hostname=self.hostname, ip=self.ip, timeout=self.timeout, method=method, url=url, headers=headers))
        outcome = FakeConnection.plan.get(self.ip, ssl.SSLEOFError('EOF occurred in violation of protocol'))
        if isinstance(outcome, BaseException):
            raise outcome
        self.outcome = outcome

    def getresponse(self):
        outcome = self.outcome
        class Response:
            status = outcome if isinstance(outcome, int) else 200
            def read(self, n): return b'' if isinstance(outcome, int) else outcome
        return Response()

    def close(self):
        pass


class DohFallbackTests(unittest.TestCase):
    def resolve(self, plan, timeout=25):
        FakeConnection.calls, FakeConnection.plan = [], plan
        with patch.object(network, '_PinnedHTTPS', FakeConnection):
            return network._doh('careers.tencent.com', timeout)

    def test_endpoints_are_cloudflare_then_alidns_then_dnspod(self):
        self.assertEqual([ip for ip, _ in network.DOH_ENDPOINTS],
                         ['1.1.1.1', '1.0.0.1', '223.5.5.5', '223.6.6.6', '1.12.12.12', '120.53.53.53'])

    def test_cloudflare_answer_stops_there(self):
        self.assertEqual(self.resolve({'1.1.1.1': answer('134.175.255.136')}), ['134.175.255.136'])
        self.assertEqual([c['ip'] for c in FakeConnection.calls], ['1.1.1.1'])
        self.assertTrue(FakeConnection.calls[0]['url'].startswith('/dns-query?'))

    def test_dropped_cloudflare_falls_back_to_alidns(self):
        self.assertEqual(self.resolve({'223.5.5.5': answer('134.175.255.136')}), ['134.175.255.136'])
        self.assertEqual([c['ip'] for c in FakeConnection.calls], ['1.1.1.1', '1.0.0.1', '223.5.5.5'])
        self.assertTrue(FakeConnection.calls[-1]['url'].startswith('/resolve?'))

    def test_dnspod_answers_when_cloudflare_and_alidns_fail(self):
        plan = {'1.0.0.1': 503, '223.5.5.5': answer(), '223.6.6.6': b'not json', '1.12.12.12': answer('1.2.3.4')}
        self.assertEqual(self.resolve(plan), ['1.2.3.4'])
        self.assertEqual([c['ip'] for c in FakeConnection.calls], ['1.1.1.1', '1.0.0.1', '223.5.5.5', '223.6.6.6', '1.12.12.12'])

    def test_only_the_hostname_is_sent_and_each_connection_is_pinned_to_its_ip(self):
        with self.assertRaises(network.FetchError):
            self.resolve({})
        self.assertEqual(len(FakeConnection.calls), 6)
        for call in FakeConnection.calls:
            self.assertEqual(call['hostname'], call['ip'])  # certificate checked against the endpoint's own IP
            self.assertEqual(call['method'], 'GET')
            self.assertEqual(parse_qs(urlsplit(call['url']).query), {'name': ['careers.tencent.com'], 'type': ['A']})
            self.assertEqual(set(call['headers']), {'Accept', 'User-Agent'})

    def test_all_failing_names_every_failure(self):
        with self.assertRaises(network.FetchError) as caught:
            self.resolve({'223.5.5.5': answer(status=3)})
        self.assertIn('公开 DNS 解析失败', str(caught.exception))
        self.assertEqual(str(caught.exception).count('SSLEOFError'), 5)

    def test_one_stalled_endpoint_cannot_use_the_whole_budget(self):
        self.resolve({'1.1.1.1': answer('1.2.3.4')})
        self.assertLessEqual(FakeConnection.calls[0]['timeout'], network.DOH_EACH_SECONDS)
        clock = iter([0, 0, 3, 3.5, 99])  # start, then the remaining-time check before each endpoint
        with patch.object(network.time, 'monotonic', lambda: next(clock)), self.assertRaises(network.FetchError):
            self.resolve({}, timeout=4)
        self.assertEqual([round(c['timeout'], 1) for c in FakeConnection.calls], [4, 1, 0.5])


if __name__ == '__main__':
    unittest.main()
