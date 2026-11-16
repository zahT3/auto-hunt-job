"""Résumé structure storage and actions (structure_get, structure_save); the rules live in profile/structure.py.

The structure sits in the Store's meta table under `resume_structure`, apart from the facts, which it never changes.
"""
import json

from ..base import Error, dumps, now
from ..profile import structure

META_KEY = 'resume_structure'
MAX_FRAGMENT_TEXT = 200


class StructureActions:
    """Résumé structure for the confirmed candidate facts, mixed into the Store."""

    def structure_stored(self, c):
        row = c.execute('SELECT value FROM meta WHERE key=?', (META_KEY,)).fetchone()
        return json.loads(row[0]) if row else None

    def structure_put(self, c, value):
        c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (META_KEY, dumps(value)))

    def structure_current(self, c=None):
        """(structure or None, candidate facts), migrated and saved. Pass an open transaction `c` or none."""
        if c is None:
            with self.tx() as c2:
                return self.structure_current(c2)
        facts = self.meta(c, 'candidate').get('facts', [])
        stored = self.structure_stored(c)
        current = structure.migrate(facts, stored)
        if current != stored and current is not None:
            self.structure_put(c, current)
        return current, facts

    def structure_get(self, payload=None):
        """The structure for the confirmed facts: a first-use pre-fill when none exists yet, stale marks when facts moved.
        `fragments` lists, per fact, the pieces of its text a field may point at."""
        current, facts = self.structure_current()
        if current is None:
            return dict(structure=None, facts=[], fragments={}, open=None)
        live = structure.confirmed(facts)
        return dict(structure=current,
                    facts=[dict(id=f['id'], version=f.get('version', 1), text=f.get('text', '')) for f in live],
                    fragments={f['id']: structure.fragments(f['text']) for f in live if len(f.get('text', '')) <= MAX_FRAGMENT_TEXT},
                    open=structure.open_items(current))

    def structure_save(self, payload):
        """Save the user's corrections. `confirm: true` marks the structure confirmed and raises its version by one; it needs
        every field settled and no stale entry. `base_version` must be the version the page loaded."""
        submitted, base = payload.get('structure'), payload.get('base_version')
        if type(base) is not int: raise Error('缺少结构版本，请刷新后重试')
        confirm = payload.get('confirm')
        if type(confirm) is not bool: raise Error('确认标记必须为布尔值')
        with self.tx() as c:
            stored = self.structure_stored(c)
            if base != (stored or {}).get('version', 0): raise Error('简历结构已被更新，请刷新后重试')
            facts = self.meta(c, 'candidate').get('facts', [])
            try:
                clean = structure.validate(submitted, facts)
            except structure.StructureError as exc:
                raise Error('简历结构有误：' + str(exc)) from exc
            if clean['version'] != base: raise Error('简历结构版本不一致，请刷新后重试')
            clean['facts_digest'] = structure.facts_digest(facts)
            if confirm:
                open_items = structure.open_items(clean)
                if open_items['uncertain'] or open_items['stale']:
                    raise Error(f"还有 {open_items['uncertain']} 个字段、{open_items['stale']} 个条目待核对，不能确认结构")
                clean.update(status='confirmed', version=base + 1, confirmed_at=now())
            else:
                clean.update(status='prefilled', confirmed_at=None)
            self.structure_put(c, clean)
            if confirm: self.intervene(c, '确认简历结构；不改变任何事实，未授权对外申请')
        return dict(structure=clean, open=structure.open_items(clean))
