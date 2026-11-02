"""Compare locally collected jobs with a hand-checked list, without fetching anything."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .normalize import normalize_company, normalize_title


SHANGHAI = timezone(timedelta(hours=8))


def _url(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError
        parts = urlsplit(value)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            raise ValueError
        # Accessing port also rejects malformed ports, without contacting the host.
        _ = parts.port
        user, at, host = parts.netloc.rpartition('@')
        netloc = user + at + host.lower()
        # A '#/...' fragment is a single-page-app route (Moka keeps the job id there); other fragments are page anchors.
        route = parts.fragment if parts.fragment.startswith('/') else ''
        return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip('/'), parts.query, route))
    except ValueError:
        raise ValueError('链接必须是有效的 HTTP(S) 地址') from None


def _time(value, label):
    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed
    except ValueError:
        raise ValueError(label + ' 必须是带时区的 ISO 8601 时间') from None


def load_truth(path):
    try:
        truth = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError('无法读取标准答案 JSON：' + str(error)) from None
    if not isinstance(truth, dict):
        raise ValueError('标准答案必须是 JSON 对象')
    if not isinstance(truth.get('direction_id'), str) or not truth['direction_id'].strip():
        raise ValueError('标准答案 direction_id 必须是非空字符串')
    _time(truth.get('collected_at'), '标准答案 collected_at')
    if not isinstance(truth.get('companies'), list):
        raise ValueError('标准答案 companies 必须是公司列表')
    for i, company in enumerate(truth['companies'], 1):
        label = '第 %d 家公司' % i
        if not isinstance(company, dict):
            raise ValueError(label + ' 必须是对象')
        if not isinstance(company.get('name'), str) or not company['name'].strip():
            raise ValueError(label + ' name 必须是非空公司名')
        try:
            if _url(company.get('careers_url')) is None:
                raise ValueError('必须提供 HTTP(S) 地址')
        except ValueError as error:
            raise ValueError(label + ' careers_url：' + str(error)) from None
        if not isinstance(company.get('jobs'), list):
            raise ValueError(label + ' jobs 必须是岗位列表')
        for n, job in enumerate(company['jobs'], 1):
            job_label = label + '第 %d 条岗位' % n
            if not isinstance(job, dict):
                raise ValueError(job_label + ' 必须是对象')
            if not isinstance(job.get('title'), str) or not job['title'].strip():
                raise ValueError(job_label + ' title 必须是非空岗位标题')
            try:
                _url(job.get('url'))
            except ValueError as error:
                raise ValueError(job_label + ' url：' + str(error)) from None
    return truth


def _ratio(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else None


def match_truth(truth, jobs):
    companies, owners, records, urls, titles = [], {}, [], {}, {}
    for i, company in enumerate(truth['companies']):
        name = normalize_company(company['name'])
        owners.setdefault(name, i)
        companies.append(dict(name=company['name'], truth=len(company['jobs']), found=0, recall=None,
                              extra=0, duplicates=0, missing=[]))
        for job in company['jobs']:
            ident = len(records)
            records.append((i, job['title']))
            titles.setdefault((name, normalize_title(job['title'])), []).append(ident)
            url = _url(job.get('url'))
            if url:
                urls.setdefault(url, []).append(ident)
    matched, seen_titles, seen_urls = set(), set(), set()
    count = closed = other = 0
    for job in jobs:
        company = normalize_company(job.get('company'))
        if company not in owners:
            other += 1
            continue
        count += 1
        closed += job.get('availability') == 'closed'
        title = normalize_title(job.get('title'))
        try:
            url = _url(job.get('url'))
        except ValueError:
            url = None
        candidates = urls.get(url) or titles.get((company, title), [])
        if candidates:
            # Prefer an unused answer within the same rule, but never fall back
            # from an already matched URL to an unrelated title match.
            ident = next((n for n in candidates if n not in matched), candidates[0])
            row = companies[records[ident][0]]
            if ident in matched:
                row['duplicates'] += 1
            else:
                matched.add(ident)
                row['found'] += 1
        else:
            row = companies[owners[company]]
            duplicate = (bool(title) and (company, title) in seen_titles) or (bool(url) and (company, url) in seen_urls)
            row['duplicates' if duplicate else 'extra'] += 1
            if title:
                seen_titles.add((company, title))
            if url:
                seen_urls.add((company, url))
    for ident, (i, title) in enumerate(records):
        if ident not in matched:
            companies[i]['missing'].append(title)
    for row in companies:
        row['recall'] = _ratio(row['found'], row['truth'])
    duplicates = sum(row['duplicates'] for row in companies)
    overall = dict(truth=len(records), found=len(matched), recall=_ratio(len(matched), len(records)), jobs=count,
                   extra=sum(row['extra'] for row in companies), duplicates=duplicates, duplicate_rate=_ratio(duplicates, count),
                   closed=closed, closed_rate=_ratio(closed, count), other_companies=other)
    return dict(direction_id=truth['direction_id'], collected_at=truth['collected_at'], overall=overall, companies=companies)


def run(truth_path, data_dir, read_jobs, direction=None, since=None, output=None):
    """read_jobs(data_dir) returns the stored jobs; it is called only after the arguments pass their checks."""
    truth_path, data_dir = Path(truth_path).resolve(), Path(data_dir).resolve()
    truth = load_truth(truth_path)
    cutoff = _time(since, '--since') if since is not None else None
    generated = datetime.now(SHANGHAI)
    output = Path(output).resolve() if output is not None else truth_path.parent / ('report-' + generated.date().isoformat() + '.json')
    if output == truth_path:
        raise ValueError('报告路径不能覆盖标准答案文件')
    jobs = []
    for i, job in enumerate(read_jobs(data_dir), 1):
        assigned = job.get('direction')
        if direction is not None and (not isinstance(assigned, dict) or assigned.get('id') != direction):
            continue
        if cutoff is not None and _time(job.get('collected_at'), '第 %d 条岗位 collected_at' % i) < cutoff:
            continue
        jobs.append(job)
    result = match_truth(truth, jobs)
    result.update(generated_at=generated.isoformat(), truth_file=str(truth_path), data_dir=str(data_dir),
                  filters=dict(direction=direction, since=since))
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError as error:
        raise ValueError('无法写入基准报告：' + str(error)) from None
    return result


def print_summary(result):
    def percent(value):
        return '不适用' if value is None else format(value, '.1%')
    row = result['overall']
    print('召回 {found}/{truth}（{recall}）· 多出 {extra} · 重复 {duplicates}（{rate}）· 已下线 {closed}'.format(
        **dict(row, recall=percent(row['recall']), rate=percent(row['duplicate_rate']))))
    for row in result['companies']:
        print('{name}：召回 {found}/{truth}（{recall}）· 多出 {extra} · 重复 {duplicates} · 未找回：{missing}'.format(
            **dict(row, recall=percent(row['recall']), missing='、'.join(row['missing']) or '无')))
