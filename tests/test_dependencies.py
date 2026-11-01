"""Dependency direction (docs: architecture roadmap, section 3), read from the source with ast; no extra dependency.

app -> workbench / ai / search / profile -> net, and every layer may use hunt/base.py. search never imports ai,
workbench or app; ai imports only search.query, profile and net. Lazy imports inside functions count too.
"""
import ast
import unittest
from pathlib import Path

HUNT = Path(__file__).resolve().parent.parent / 'hunt'
LAYERS = ('base', 'net', 'search', 'profile', 'ai', 'workbench', 'app')
ALLOWED = dict(base=set(), net={'base'}, search={'net', 'base'}, profile={'net', 'base'},
               ai={'profile', 'net', 'base'}, workbench={'search', 'profile', 'net', 'base'}, app=set(LAYERS))
# The one module of another layer that ai may read: the search-term logic it shares with the sources.
OPEN_TO_AI = 'search.query'
# The package's own entry modules; every other module sits in its layer's package.
FLAT = {'': 'app', '__main__': 'app'}


def module_name(path):
    parts = list(path.relative_to(HUNT).with_suffix('').parts)
    if parts[-1] == '__init__': parts.pop()
    return '.'.join(parts)


def exists(name):
    base = HUNT.joinpath(*name.split('.')) if name else HUNT
    return base.with_suffix('.py').is_file() or (base / '__init__.py').is_file()


def imports(path):
    """Modules inside hunt that one file imports, at any depth of the file."""
    name, found = module_name(path), set()
    package = name if path.name == '__init__.py' else name.rpartition('.')[0]
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            targets = [a.name[5:] for a in node.names if a.name.startswith('hunt.')]
            found.update(t for t in targets if exists(t))
            continue
        if not isinstance(node, ast.ImportFrom): continue
        if node.level:
            bits = package.split('.') if package else []
            bits = bits[:len(bits) - (node.level - 1)] if node.level > 1 else bits
            origin = '.'.join(bits + ([node.module] if node.module else []))
        elif node.module == 'hunt' or (node.module or '').startswith('hunt.'):
            origin = node.module[5:]
        else:
            continue
        for alias in node.names:
            child = (origin + '.' if origin else '') + alias.name
            found.add(child if exists(child) else origin)
    found.discard(name)
    return found


def graph():
    return {module_name(p): imports(p) for p in sorted(HUNT.rglob('*.py'))}


def layer(name):
    top = name.split('.')[0]
    if top in LAYERS: return top
    return FLAT.get(name, FLAT.get(top))


def allowed(source, target):
    a, b = layer(source), layer(target)
    if a == b or b in ALLOWED[a]: return True
    return a == 'ai' and (target == OPEN_TO_AI or target.startswith(OPEN_TO_AI + '.'))


def cyclic(edges):
    """Modules on some import cycle (strongly connected components larger than one, Tarjan)."""
    index, low, stack, on, result, counter = {}, {}, [], set(), set(), [0]
    def visit(v):
        index[v] = low[v] = counter[0]; counter[0] += 1
        stack.append(v); on.add(v)
        for w in edges.get(v, ()):
            if w not in index:
                visit(w); low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop(); on.discard(w); component.append(w)
                if w == v: break
            if len(component) > 1: result.update(component)
    for v in sorted(edges):
        if v not in index: visit(v)
    return result


class DependencyDirectionTests(unittest.TestCase):
    def test_every_module_has_a_layer(self):
        self.assertEqual([m for m in graph() if layer(m) is None], [])
        self.assertEqual([m for m in FLAT if m and not exists(m)], [], 'FLAT names a module that has moved')

    def test_imports_point_down_the_layers(self):
        found = {(a, b) for a, targets in graph().items() for b in targets if not allowed(a, b)}
        self.assertEqual(sorted(found), [], 'import against the layer direction')

    def test_no_import_cycles(self):
        self.assertEqual(sorted(cyclic(graph())), [], 'modules on an import cycle')

    def test_direction_rules(self):
        for source, target, ok in (('search.engine', 'ai.llm', False), ('search.parse', 'workbench.export', False),
                                   ('ai.orient', 'search.query', True), ('ai.orient', 'search.engine', False),
                                   ('workbench.actions', 'search.sources.anker', True), ('net.network', 'base', True),
                                   ('profile.profile', 'search.query', False), ('app.store', 'workbench.actions', True)):
            self.assertIs(allowed(source, target), ok, (source, target))

    def test_reader_resolves_relative_lazy_and_absolute_imports(self):
        import tempfile
        global HUNT
        saved = HUNT
        with tempfile.TemporaryDirectory() as tmp:
            HUNT = Path(tmp)
            try:
                for name, text in (('__init__.py', ''), ('a.py', 'def f():\n    from .b import x\n'), ('b.py', 'import hunt.a\n'),
                                   ('p/__init__.py', 'from .. import a\n'), ('p/q.py', 'from . import thing\nfrom hunt.p import q\n')):
                    (HUNT / name).parent.mkdir(exist_ok=True)
                    (HUNT / name).write_text(text)
                self.assertEqual(graph(), {'': set(), 'a': {'b'}, 'b': {'a'}, 'p': {'a'}, 'p.q': {'p'}})
                self.assertEqual(cyclic(graph()), {'a', 'b'})
            finally:
                HUNT = saved


if __name__ == '__main__':
    unittest.main()
