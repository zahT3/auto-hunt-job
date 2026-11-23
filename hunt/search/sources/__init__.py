"""Source-module registry: the search engine routes each configured source to a Provider.

A new source is a module `hunt/search/sources/<id>.py` that calls `register(Provider(...))`;
every submodule is imported when this package loads. Source modules import hunt.search.parse,
hunt.net, hunt.search.query and each other, never the engine: it only orchestrates.
"""
import importlib
import pkgutil
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from ..parse import SourceError


class Context:
    """What a provider may use: the budgeted reader, search terms, quotas and the source report.

    keep(job), when set, is a local check for remote keyword search: a job it rejects is dropped before it counts
    toward `limit` and tallied in report['filtered'] (a sweep uses it so loose remote matches cannot take job slots)."""
    def __init__(self, read, terms, limit, pages, report, renderer=None, keep=None):
        self.read, self.terms, self.limit, self.pages, self.report, self.renderer = read, terms, limit, pages, report, renderer
        self.keep = keep


def _no_detect(entry): return None


@dataclass(frozen=True)
class Provider:
    id: str
    fetch: Callable[[dict, Context], Iterator[dict]]
    detect: Callable[[dict], Optional[dict]] = _no_detect
    probe_mode: str = ''  # remote, literal or local; empty for readers without direction probes


REGISTRY: dict = {}

MAX_DETAIL_ERRORS = 20


def record_detail_error(report, platform_id, error):
    """Skip-and-record for one bad post, so it cannot discard the rest of a large board.

    discover() turns the recorded errors into a counted parse_error; only MAX_DETAIL_ERRORS
    are kept, `detail_error_count` holds the true total.
    """
    report['detail_error_count'] = report.get('detail_error_count', 0) + 1
    errors = report.setdefault('detail_errors', [])
    if len(errors) < MAX_DETAIL_ERRORS:
        errors.append(dict(platform_id=platform_id, status='parse_error', error=str(error)))


class PagedJobs(Iterator):
    """A keyword reader's in-memory cursor. A new batch can finish a partly consumed page."""
    def __init__(self, ctx, fetch_page, make_job, row_id, page_size):
        self.fetch_page, self.make_job, self.row_id = fetch_page, make_job, row_id
        self.page_size, self.keep = page_size, ctx.keep
        self.next_page = dict.fromkeys(ctx.terms, 1)
        self.pending = {}
        self.seen = set()
        self.resume(ctx.limit, ctx.pages, ctx.report)

    def __next__(self):
        return next(self.batch)

    def has_work(self, pages):
        return bool(self.pending) or any(page is not None and page <= pages for page in self.next_page.values())

    def resume(self, limit, pages, report):
        self.batch = self._read(limit, pages, report)

    def _read(self, limit, pages, report):
        count = 0
        # Drain an already paid-for page even when the shared request budget has just run out.
        for term in sorted(self.next_page, key=lambda term: term not in self.pending):
            while True:
                if term not in self.pending:
                    page = self.next_page[term]
                    if page is None: break
                    if page > pages:
                        report['truncated'] = True
                        if 'truncation_reason' in report: report['truncation_reason'] = 'page_limit'
                        break
                    posts, total = self.fetch_page(term, page)
                    report['pages'] += 1
                    report['fetched'] += len(posts)
                    self.next_page[term] = page + 1 if posts and page * self.page_size < total else None
                    self.pending[term] = deque(posts)
                rows = self.pending[term]
                while rows:
                    row = rows.popleft()
                    try:
                        job = self.make_job(row)
                    except SourceError as e:
                        if e.status != 'parse_error': raise
                        record_detail_error(report, self.row_id(row), e)
                        continue
                    ident = job['platform_id']
                    if ident in self.seen: continue
                    if self.keep and not self.keep(job):
                        self.seen.add(ident)
                        report['filtered'] = report.get('filtered', 0) + 1
                        continue
                    if count >= limit:
                        rows.appendleft(row)
                        report['truncated'] = True
                        if 'truncation_reason' in report: report['truncation_reason'] = 'job_share'
                        return
                    self.seen.add(ident)
                    count += 1
                    yield job
                del self.pending[term]


def paged_jobs(ctx, fetch_page, make_job, row_id, page_size):
    return PagedJobs(ctx, fetch_page, make_job, row_id, page_size)


def register(provider):
    REGISTRY[provider.id] = provider
    return provider


def route(entry):
    kind = entry.get('kind')
    provider = REGISTRY.get(kind) if isinstance(kind, str) else None
    if provider: return provider
    for provider in list(REGISTRY.values()):
        if provider.detect(entry) is not None: return provider
    return None


def load_all():
    for module in pkgutil.iter_modules(__path__):
        importlib.import_module(__name__ + '.' + module.name)


load_all()
