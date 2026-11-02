"""The job library: searchable columns over the stored jobs, full-text search, freshness and cross-source groups.

jobs.data keeps the whole JSON record as the detail. The other columns are derived from it on every write through this
module, so they cannot drift; first_seen, last_seen, status and missed belong to the index alone. Every read and write
of the jobs table goes through here, and schema changes go through migrate() and meta.schema_version.
"""
import json
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from ..base import Error, digest, dumps, now
from .normalize import normalize_company, normalize_title
from .query import matches

SCHEMA_VERSION = 2
# A job closes after this many consecutive clean rounds of its source without it.
CLOSE_AFTER = 2
# Source report statuses that mean the source read everything it was asked for; a truncated report never counts.
CLEAN = ('ok', 'empty', 'filtered_empty')
DERIVED = ('company', 'title', 'city', 'source', 'source_id', 'platform_id', 'direction', 'group_key', 'jd_digest')
UNKNOWN_COMPANY = ('', '待确认')
MAX_LIMIT = 500

_CITIES = ('北京|上海|天津|重庆|深圳|广州|杭州|南京|成都|武汉|西安|苏州|郑州|长沙|青岛|宁波|无锡|合肥|厦门|福州|济南|大连|沈阳|哈尔滨|'
           '长春|石家庄|太原|南昌|昆明|贵阳|南宁|海口|兰州|西宁|银川|乌鲁木齐|呼和浩特|拉萨|佛山|东莞|珠海|中山|惠州|常州|南通|徐州|'
           '温州|嘉兴|绍兴|金华|台州|烟台|潍坊|临沂|洛阳|唐山|保定|泉州|漳州|扬州|镇江|盐城|芜湖|襄阳|宜昌|株洲|湘潭|岳阳|柳州|桂林|'
           '三亚|汕头|江门|湛江|肇庆|绵阳|德阳|遵义|香港|澳门|台北|新加坡').split('|')
_ENGLISH = {'beijing': '北京', 'shanghai': '上海', 'shenzhen': '深圳', 'guangzhou': '广州', 'hangzhou': '杭州', 'chengdu': '成都',
            'wuhan': '武汉', 'nanjing': '南京', 'suzhou': '苏州', 'xian': '西安', "xi'an": '西安', 'tianjin': '天津',
            'chongqing': '重庆', 'xiamen': '厦门', 'hefei': '合肥', 'changsha': '长沙', 'qingdao': '青岛', 'zhuhai': '珠海',
            'dongguan': '东莞', 'hong kong': '香港', 'hongkong': '香港', 'taipei': '台北', 'singapore': '新加坡'}
_CITY_RE = re.compile('|'.join(sorted(_CITIES, key=len, reverse=True)) + '|' +
                      '|'.join(r'(?<![a-z])' + re.escape(k) + r'(?![a-z])' for k in sorted(_ENGLISH, key=len, reverse=True)))
_SEPARATORS = re.compile(r'[/,，、;；|·\s]+')
_NO_PLACE = ('未知', '待确认', '待补充', '地点未知', 'unknown', 'n/a')


def cities(location):
    """Known city names in a location string, in order ('广东省深圳市南山区' -> ['深圳']); an unlisted place keeps its first part."""
    text = unicodedata.normalize('NFKC', str(location or '')).casefold()
    found = list(dict.fromkeys(_ENGLISH.get(m.group(0), m.group(0)) for m in _CITY_RE.finditer(text)))
    if found: return found
    first = next((p for p in _SEPARATORS.split(text) if p), '')
    first = re.sub(r'(?:省|市)$', '', first)
    return [first] if first and first not in _NO_PLACE and not any(w in first for w in _NO_PLACE) else []


def group_key(company, title, city):
    """Same canonical company, title and city: a candidate link between sources. Unknown company or title: no key.
    search() links a key's jobs only when each source holds one of them."""
    company, title = normalize_company(company), normalize_title(title)
    if company in UNKNOWN_COMPANY or not title: return None
    return 'g' + digest([company, title, sorted((city or '').split('/'))])[:16]


def discovered_identity(item):
    """The identity Store.import_job gives a discovered job, which always carries platform_id."""
    if not item.get('platform_id'): return None
    return str(item.get('channel', 'import')) + ':' + str(item['platform_id'])


def _derived(job):
    raw = job.get('raw') if isinstance(job.get('raw'), dict) else {}
    found = raw.get('discovery') if isinstance(raw.get('discovery'), dict) else {}
    direction = job.get('direction') if isinstance(job.get('direction'), dict) else {}
    company, title = str(job.get('company') or '').strip(), str(job.get('title') or '').strip()
    city = '/'.join(cities(job.get('location'))) or None
    pid = job.get('platform_id')
    return dict(company=company or None, title=title, city=city, source=job.get('channel'), source_id=found.get('source_id'),
                platform_id=None if pid is None else str(pid), direction=direction.get('id'),
                group_key=group_key(company, title, city), jd_digest=digest(job.get('jd')))


def _seen_times(job):
    """First and last time a stored record shows its job was seen, for rows written before the index existed."""
    def parse(value):
        try:
            moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return (moment if moment.utcoffset() is not None else moment.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except ValueError:
            return None
    first = parse(job.get('collected_at'))
    times = [parse(e.get('time')) for e in job.get('events') or [] if isinstance(e, dict) and e.get('kind') in ('imported', 'deduplicated', 'source_changed')]
    times += [parse((job.get('latest_observation') or {}).get('time'))] if isinstance(job.get('latest_observation'), dict) else []
    times = [t for t in times + [first] if t]
    if not times: return now(), now()
    stamp = lambda t: t.isoformat(timespec='microseconds')
    return stamp(first or min(times)), stamp(max(times))


def has_fts(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE name='jobs_fts'").fetchone() is not None


def _to_v2(c):
    have = {r[1] for r in c.execute('PRAGMA table_info(jobs)')}
    for name, decl in (*((n, 'TEXT') for n in DERIVED), ('first_seen', 'TEXT'), ('last_seen', 'TEXT'),
                       ('status', "TEXT NOT NULL DEFAULT 'open'"), ('missed', 'INTEGER NOT NULL DEFAULT 0')):
        if name not in have: c.execute('ALTER TABLE jobs ADD COLUMN %s %s' % (name, decl))
    c.execute('CREATE INDEX IF NOT EXISTS jobs_group ON jobs(group_key)')
    c.execute('CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source_id, status)')
    c.execute('CREATE INDEX IF NOT EXISTS jobs_jd ON jobs(jd_digest)')
    try:
        # trigram matches any substring of 3+ characters, which Chinese titles need (no word boundaries).
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(title, jd, tokenize='trigram')")
    except sqlite3.OperationalError:
        pass  # SQLite without FTS5 or trigram: search() falls back to LIKE over the same text
    fts = has_fts(c)
    for rowid, data in c.execute('SELECT rowid, data FROM jobs').fetchall():
        job = json.loads(data)
        first, last = _seen_times(job)
        cols = _derived(job)
        c.execute('UPDATE jobs SET %s, first_seen=?, last_seen=?, status=? WHERE rowid=?' % ', '.join(k + '=?' for k in cols),
                  (*cols.values(), first, last, 'closed' if job.get('availability') == 'closed' else 'open', rowid))
        if fts: c.execute('INSERT INTO jobs_fts(rowid, title, jd) VALUES(?,?,?)', (rowid, cols['title'], str(job.get('jd') or '')))


STEPS = {2: _to_v2}


def migrate(c):
    """Bring the jobs table to SCHEMA_VERSION inside the caller's transaction. A library without meta.schema_version
    is version 1: jobs(id, identity, data) only, as every library before the index."""
    c.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, data TEXT NOT NULL)')
    row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    version = json.loads(row[0]) if row else 1
    if version > SCHEMA_VERSION: raise Error('数据目录由更新版本的程序写入（库版本 %s），请升级程序后再打开' % version)
    for target in range(version + 1, SCHEMA_VERSION + 1):
        STEPS[target](c)
    c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('schema_version', dumps(SCHEMA_VERSION)))
    return version


def _index_text(c, job, rowid=None):
    if not has_fts(c): return
    rowid = rowid or c.execute('SELECT rowid FROM jobs WHERE id=?', (job['id'],)).fetchone()[0]
    title, jd = str(job.get('title') or ''), str(job.get('jd') or '')
    if c.execute('SELECT 1 FROM jobs_fts WHERE rowid=? AND title=? AND jd=?', (rowid, title, jd)).fetchone(): return
    c.execute('DELETE FROM jobs_fts WHERE rowid=?', (rowid,))
    c.execute('INSERT INTO jobs_fts(rowid, title, jd) VALUES(?,?,?)', (rowid, title, jd))


def insert(c, job, identity, at=None):
    at = at or now()
    cols = _derived(job)
    c.execute('INSERT INTO jobs(id, identity, data, %s, first_seen, last_seen, status) VALUES(?,?,?,%s,?,?,?)'
              % (', '.join(cols), ','.join('?' * len(cols))),
              (job['id'], identity, dumps(job), *cols.values(), at, at, 'closed' if job.get('availability') == 'closed' else 'open'))
    _index_text(c, job)


def save(c, job):
    """Write the JSON back; a source saying the job is closed closes it, anything else leaves the index status alone."""
    cols = _derived(job)
    c.execute("UPDATE jobs SET data=?, %s, status=CASE WHEN ?='closed' THEN 'closed' ELSE status END WHERE id=?"
              % ', '.join(k + '=?' for k in cols), (dumps(job), *cols.values(), job.get('availability'), job['id']))
    _index_text(c, job)


def get(c, job_id):
    row = c.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
    return json.loads(row[0]) if row else None


def find(c, identity):
    """The id of the job stored under this identity, or None."""
    row = c.execute('SELECT id FROM jobs WHERE identity=?', (identity,)).fetchone()
    return row[0] if row else None


def same_text(c, jd):
    """True when a stored job has exactly this JD text."""
    return c.execute('SELECT 1 FROM jobs WHERE jd_digest=? LIMIT 1', (digest(jd),)).fetchone() is not None


def all_jobs(c, newest_first=True):
    return [json.loads(r[0]) for r in c.execute('SELECT data FROM jobs ORDER BY rowid ' + ('DESC' if newest_first else 'ASC'))]


def observe(c, items, sources, terms, at=None):
    """Record one search round. Every job the round returned is seen now (and reopens). For each source that finished
    cleanly, an open job of that source the round did not return counts a miss, and closes at CLOSE_AFTER consecutive
    misses. A miss counts only when the round's terms still match the job's title: a round searching for something
    else says nothing about it."""
    at = at or now()
    seen = {i for i in map(discovered_identity, items) if i}
    touched = 0
    for identity in seen:
        touched += c.execute("UPDATE jobs SET last_seen=?, missed=0, status=CASE WHEN json_extract(data, '$.availability')='closed' "
                             "THEN 'closed' ELSE 'open' END WHERE identity=?", (at, identity)).rowcount
    clean = sorted({s.get('source_id') for s in sources if s.get('status') in CLEAN and not s.get('truncated') and s.get('source_id')})
    missed = closed = 0
    for source_id in clean:
        for jid, identity, title, count in c.execute("SELECT id, identity, title, missed FROM jobs WHERE source_id=? AND status='open'",
                                                     (source_id,)).fetchall():
            if identity in seen or not matches(title or '', terms): continue
            missed += 1
            gone = count + 1 >= CLOSE_AFTER
            closed += gone
            c.execute('UPDATE jobs SET missed=?, status=? WHERE id=?', (count + 1, 'closed' if gone else 'open', jid))
    return dict(seen=touched, missed=missed, closed=closed, clean_sources=clean, close_after=CLOSE_AFTER)


def query_terms(q):
    return [t for t in _SEPARATORS.split(unicodedata.normalize('NFKC', str(q or '')).strip()) if t][:8]


def _like(term):
    return '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


ROW = ("j.rowid, j.id, j.company, j.title, j.city, j.source, j.source_id, j.platform_id, j.direction, j.group_key, j.first_seen, "
       "j.last_seen, j.status, json_extract(j.data, '$.url'), json_extract(j.data, '$.application_url'), "
       "json_extract(j.data, '$.salary'), json_extract(j.data, '$.location')")
FIELDS = ('rowid', 'job_id', 'company', 'title', 'city', 'source', 'source_id', 'platform_id', 'direction', 'group',
          'first_seen', 'last_seen', 'status', 'url', 'application_url', 'salary', 'location')


def search(c, q='', city=None, direction=None, source=None, fresh=None, limit=50):
    """Jobs matching every word of q in the title or JD, grouped by group_key; each group lists all its sources.

    Words of 3+ characters use the trigram index; shorter ones ('AI', '产品') fall back to LIKE. city matches one of a
    job's cities, source a channel ('liepin') or a source id ('feishu:...'), direction a classified direction id, and
    fresh=N keeps open jobs seen in the last N days. Groups rank open first, then all words in the title, then newest."""
    began = time.monotonic()
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT: raise Error('limit 必须是 1 至 %d' % MAX_LIMIT)
    if fresh is not None and (not isinstance(fresh, int) or isinstance(fresh, bool) or not 1 <= fresh <= 3650):
        raise Error('fresh 必须是 1 至 3650 天')
    words = query_terms(q)
    where, args = [], []
    fts = has_fts(c)
    long_words = [w for w in words if len(w) >= 3] if fts else []
    if long_words:
        where.append('j.rowid IN (SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?)')
        args.append(' AND '.join('"%s"' % w.replace('"', '""') for w in long_words))
    for word in words:
        if word in long_words: continue
        if fts: where.append("j.rowid IN (SELECT rowid FROM jobs_fts WHERE title LIKE ? ESCAPE '\\' OR jd LIKE ? ESCAPE '\\')")
        else: where.append("(j.title LIKE ? ESCAPE '\\' OR json_extract(j.data, '$.jd') LIKE ? ESCAPE '\\')")
        args += [_like(word)] * 2
    place = (cities(city) or [None])[0] if city else None
    if city:
        where.append("instr('/' || coalesce(j.city, '') || '/', ?) > 0"); args.append('/' + (place or str(city).strip()) + '/')
    if direction:
        where.append('j.direction=?'); args.append(direction)
    if source:
        where.append('(j.source=? OR j.source_id=?)'); args += [source, source]
    if fresh is not None:
        where.append("j.status='open' AND j.last_seen>=?")
        args.append((datetime.now(timezone.utc) - timedelta(days=fresh)).isoformat(timespec='microseconds'))
    sql = 'SELECT %s FROM jobs j%s' % (ROW, ' WHERE ' + ' AND '.join(where) if where else '')
    hits = [dict(zip(FIELDS, r)) for r in c.execute(sql, args)]
    folded = [w.casefold() for w in words]
    keyed = {}
    for hit in hits:
        hit['matched'] = True
        hit['title_match'] = all(w in unicodedata.normalize('NFKC', hit['title'] or '').casefold() for w in folded)
        keyed.setdefault(hit['group'] or 'job:' + hit['job_id'], []).append(hit)
    keys = [k for k in keyed if not k.startswith('job:')]
    matched = {h['job_id'] for h in hits}
    for start in range(0, len(keys), 500):
        part = keys[start:start + 500]
        for r in c.execute('SELECT %s FROM jobs j WHERE j.group_key IN (%s)' % (ROW, ','.join('?' * len(part))), part):
            member = dict(zip(FIELDS, r))
            if member['job_id'] not in matched:
                keyed[member['group']].append(dict(member, matched=False, title_match=False))
    groups = {}
    for key, members in keyed.items():
        # One source listing two jobs under the same key means they are distinct postings (one employer often opens the
        # same title several times); which of them another source's copy is cannot be told, so none of them link.
        sources = [m['source'] for m in members]
        if len(set(sources)) == len(sources): groups[key] = members
        else: groups.update(('job:' + m['job_id'], [m]) for m in members if m['matched'])

    def shown(key, members):
        best = max((m for m in members if m['matched']), key=lambda m: (m['status'] == 'open', m['title_match'], m['last_seen'] or '', m['rowid']))
        members.sort(key=lambda m: (not m['matched'], m['status'] != 'open', -(m['rowid'])))
        return dict(group=key, title=best['title'], company=best['company'], city=best['city'],
                    status='open' if any(m['status'] == 'open' for m in members) else 'closed',
                    title_match=best['title_match'], direction=best['direction'],
                    first_seen=min(m['first_seen'] or '' for m in members), last_seen=max(m['last_seen'] or '' for m in members),
                    sources=[{k: m[k] for k in FIELDS + ('matched',) if k not in ('rowid', 'group', 'company', 'title', 'city')}
                             for m in members],
                    _rank=(best['status'] == 'open', best['title_match'], best['last_seen'] or '', best['rowid']))
    rows = sorted((shown(k, v) for k, v in groups.items()), key=lambda g: g['_rank'], reverse=True)
    for row in rows: del row['_rank']
    return dict(schema_version=1, query=dict(q=str(q or ''), words=words, city=place or city, direction=direction, source=source,
                                             fresh=fresh, limit=limit),
                total_groups=len(rows), total_jobs=len(hits), groups=rows[:limit], full_text=fts,
                elapsed_ms=round((time.monotonic() - began) * 1000, 1),
                note='只查本机岗位库；岗位在本机库里的状态，不等于招聘方是否仍在招。')
