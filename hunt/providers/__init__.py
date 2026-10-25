"""Source-module registry: discovery routes each configured source to a Provider.

A new source is a module `hunt/providers/<id>.py` that calls `register(Provider(...))`;
every submodule is imported when this package loads. Provider modules import hunt.sources /
hunt.network at module level and hunt.discovery only lazily (it is still importing when
load_all() runs).
"""
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from ..sources import SourceError


class Context:
    """What a provider may use: the budgeted reader, search terms, quotas and the source report."""
    def __init__(self, read, terms, limit, pages, report, renderer=None):
        self.read, self.terms, self.limit, self.pages, self.report, self.renderer = read, terms, limit, pages, report, renderer


def _no_detect(entry): return None


@dataclass(frozen=True)
class Provider:
    id: str
    fetch: Callable[[dict, Context], Iterator[dict]]
    detect: Callable[[dict], Optional[dict]] = _no_detect


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


def paged_jobs(ctx, fetch_page, make_job, row_id, page_size):
    """The per-keyword paging loop shared by the paged JSON providers.

    fetch_page(term, page) -> (posts, total) does the request and sets report['search_url'];
    make_job(row) raises SourceError('parse_error') for a bad post, which is recorded and skipped
    (row_id(row) names it, or None). Jobs are deduped by platform_id across keywords; `truncated`
    is set only when a further new job (or page) existed beyond ctx.limit / ctx.pages.
    """
    seen, count = set(), 0
    for term in ctx.terms:
        for page in range(1, ctx.pages + 1):
            posts, total = fetch_page(term, page)
            ctx.report['pages'] += 1; ctx.report['fetched'] += len(posts)
            for row in posts:
                try: job = make_job(row)
                except SourceError as e:
                    if e.status != 'parse_error': raise
                    record_detail_error(ctx.report, row_id(row), e)
                    continue
                if job['platform_id'] in seen: continue
                if count >= ctx.limit: ctx.report['truncated'] = True; return
                seen.add(job['platform_id']); count += 1
                yield job
            if not posts or page * page_size >= total: break
            if page == ctx.pages: ctx.report['truncated'] = True


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


def _discovery():
    # Imported at call time: discovery imports this package.
    from .. import discovery
    return discovery


def _fetcher(name, *, renderer=False):
    def fetch(entry, ctx):
        function = getattr(_discovery(), name)
        args = (entry, ctx.read, ctx.terms, ctx.limit, ctx.pages, ctx.report)
        return function(*args, ctx.renderer) if renderer else function(*args)
    return fetch


for _id, _function in (('greenhouse', '_api'), ('lever', '_api'), ('ashby', '_api'), ('boss', '_platform'),
                       ('liepin', '_platform'), ('anker', '_anker'), ('websearch', '_websearch')):
    register(Provider(_id, _fetcher(_function)))
register(Provider('website', _fetcher('_website', renderer=True)))


def load_all():
    for module in pkgutil.iter_modules(__path__):
        importlib.import_module(__name__ + '.' + module.name)


load_all()
