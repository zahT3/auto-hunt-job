import unittest
from types import SimpleNamespace
from unittest.mock import patch
from hunt import providers
from hunt.providers import Provider, REGISTRY, register, route
from hunt.discovery import discover


class ProviderRegistryTests(unittest.TestCase):
    def test_existing_kinds_registered(self):
        for pid in ('greenhouse', 'lever', 'ashby', 'boss', 'liepin', 'anker', 'website', 'websearch'):
            self.assertIn(pid, REGISTRY)
            self.assertEqual(REGISTRY[pid].id, pid)

    def test_route_prefers_explicit_kind(self):
        self.assertIs(route(dict(kind='lever', board='x')), REGISTRY['lever'])

    def test_route_uses_detect(self):
        def detect(entry):
            if 'example.test' in (entry.get('careers_url') or ''): return dict(entry, kind='probe-test')
        probe = Provider(id='probe-test', detect=detect, fetch=lambda entry, ctx: iter(()))
        with patch.dict(REGISTRY):
            register(probe)
            self.assertIs(route(dict(careers_url='https://jobs.example.test')), probe)
            self.assertIsNone(route(dict(careers_url='https://jobs.other.test')))
        self.assertNotIn('probe-test', REGISTRY)

    def test_unknown_kind_reports_not_configured(self):
        result = discover(dict(keywords=['AI'], discovery_sources=[dict(kind='nope')]), transport=lambda u, **kw: b'{}')
        self.assertEqual(result['sources'][0]['status'], 'not_configured')

    def test_load_all_imports_every_submodule(self):
        with patch('pkgutil.iter_modules', return_value=[SimpleNamespace(name='demo')]), \
             patch('importlib.import_module') as load:
            providers.load_all()
        load.assert_called_once_with('hunt.providers.demo')


if __name__ == '__main__':
    unittest.main()
