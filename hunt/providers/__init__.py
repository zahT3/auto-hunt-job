"""Source-module registry: discovery routes each configured source to a Provider.

A new source is a module `hunt/providers/<id>.py` that calls `register(Provider(...))`;
every submodule is imported when this package loads.
"""
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable, Iterator, Optional


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


def register(provider):
    REGISTRY[provider.id] = provider
    return provider


def route(entry):
    provider = REGISTRY.get(entry.get('kind'))
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
