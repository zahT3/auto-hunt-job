"""Shared read-only employer metadata for discovery and classification of previously imported jobs."""
import functools
import json
from pathlib import Path


DATA = Path(__file__).resolve().parents[1] / 'data' / 'companies.cn.json'


@functools.lru_cache(maxsize=4)
def seed_rows(path):
    return tuple(json.loads(path.read_text(encoding='utf-8'))['companies'])


@functools.lru_cache(maxsize=1)
def _indexes():
    rows = seed_rows(DATA)
    return {r['id']: r for r in rows}, {r['name']: r for r in rows}


def seed_for(source_id, company):
    by_id, by_name = _indexes()
    return by_id.get(source_id) or by_name.get(company) or {}


def job_source(job):
    raw = job.get('raw')
    discovery = raw.get('discovery') if isinstance(raw, dict) else None
    if not isinstance(discovery, dict):
        discovery = {}
    return {**seed_for(discovery.get('source_id'), job.get('company')), **discovery}
