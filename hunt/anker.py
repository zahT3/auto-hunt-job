"""Anker's official public recruiting source. Remote text is data only."""
import json
import re
from datetime import datetime, timezone
from .network import fetch, FetchError

WEBSITE = '6962795203808168199'  # 社会招聘; official site's page-data configuration.
BASE = 'https://open.anker-in.com/service'
CAREER = 'https://career.anker.com.cn'


class ChannelError(ValueError):
    pass


def platform_id(value):
    value = str(value)
    # List IDs concatenate post ID + website ID; details/apply use the post ID.
    if value.endswith(WEBSITE) and len(value) > len(WEBSITE):
        value = value[:-len(WEBSITE)]
    if not re.fullmatch(r'[0-9]{15,25}', value):
        raise ChannelError('安克岗位 ID 无效')
    return value


def _name(obj):
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return obj.get('zh_cn') or obj.get('zhCn') or obj.get('en_us') or obj.get('enUs') or ''
    return ''


def _title_matches(title, keyword):
    """Explicit title terms only; the upstream endpoint also matches substrings.

    ASCII boundaries stop AI from matching maintain/sustaining. Chinese titles
    can have AI adjacent to Han characters, so Unicode word boundaries do not fit.
    """
    term = keyword.strip()
    if not term:
        return True
    pattern = re.escape(term)
    if term[0].isascii() and term[0].isalnum():
        pattern = r'(?<![A-Za-z0-9_])' + pattern
    if term[-1].isascii() and term[-1].isalnum():
        pattern += r'(?![A-Za-z0-9_])'
    return re.search(pattern, str(title), flags=re.IGNORECASE) is not None


def _json(raw):
    try:
        result = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ChannelError('安克公开接口解析失败；保留本轮失败原因，不回退为模拟岗位') from exc
    if not isinstance(result, dict) or result.get('code') != 200:
        raise ChannelError('安克公开接口返回业务失败：' + str(result.get('code') if isinstance(result, dict) else 'invalid'))
    return result


class Anker:
    def __init__(self, transport=None):
        self.transport = transport or fetch
        self.last_discovery = None

    def discover(self, limit=5, keyword=''):
        if not 1 <= int(limit) <= 5:
            raise ChannelError('每轮发现上限为 1 至 5 个岗位')
        if not isinstance(keyword, str) or len(keyword) > 200:
            raise ChannelError('岗位关键词无效')
        url = BASE + '/lark/openapi/getJobPosts/' + WEBSITE + '?page=1&size=' + str(int(limit))
        payload = dict(job_function_id=[], city_code=[], subject_id=[], language_key=[], keywords=keyword)
        response = _json(self.transport(url, method='POST', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}))
        rows = response.get('data')
        if not isinstance(rows, list):
            raise ChannelError('安克岗位列表结构变化；未把解析失败当作无结果')
        scanned = rows[:int(limit)]
        self.last_discovery = dict(url=url, total=response.get('total'), fetched_at=datetime.now(timezone.utc).isoformat(),
                                   fetched_count=len(scanned), retained_count=0, keyword=keyword,
                                   filter_mode='title_keyword' if keyword.strip() else 'none',
                                   candidates=[], excluded=[], raw_records=scanned)
        result = []
        for row in scanned:
            if not isinstance(row, dict) or not row.get('id'):
                raise ChannelError('安克岗位缺少稳定 ID')
            pid = platform_id(row['id'])
            candidate = dict(platform_id=pid, title=row.get('title', ''))
            self.last_discovery['candidates'].append(candidate)
            if not _title_matches(row.get('title', ''), keyword):
                self.last_discovery['excluded'].append(dict(candidate, reason='标题未明确包含该关键词；上游可能仅正文或英文子串命中'))
                continue
            item = self.detail(pid)
            item['raw']['list_record'] = row
            item['raw']['discovery_url'] = url
            item['raw']['keyword_filter'] = dict(mode=self.last_discovery['filter_mode'], keyword=keyword,
                                                source_fetched_count=len(scanned), note='仅核对标题关键词，不代表目标适配或胜任要求')
            if item['status'] != 'open':
                self.last_discovery['excluded'].append(dict(candidate, reason='详情未确认当前在招'))
            elif not _title_matches(item['title'], keyword):
                self.last_discovery['excluded'].append(dict(candidate, reason='最新详情标题不再包含关键词，需核对索引变化'))
            else:
                result.append(item)
        self.last_discovery['retained_count'] = len(result)
        self.last_discovery['status'] = 'retained' if result else 'filtered_empty' if scanned else 'empty'
        return result

    def detail(self, post_id):
        post_id = platform_id(post_id)
        url = BASE + '/openapi/getJobPostDetail/' + WEBSITE + '?jobPostId=' + post_id
        response = _json(self.transport(url))
        row = response.get('data')
        if not isinstance(row, dict) or not row.get('id'):
            raise ChannelError('岗位已下线或详情结构变化，未获得可核对详情')
        if str(row['id']) != post_id or not row.get('title'):
            raise ChannelError('安克详情岗位身份不符')
        addresses = row.get('address_list') or [row.get('address', {})]
        cities = list(dict.fromkeys(_name(a.get('city', {}).get('name')) for a in addresses if isinstance(a, dict)))
        location = '、'.join(c for c in cities if c) or None
        description, requirements = row.get('description') or '', row.get('requirement') or ''
        if not isinstance(description, str) or not isinstance(requirements, str) or not (description or requirements):
            raise ChannelError('安克详情缺少可用原文')
        return dict(channel='anker', platform_id=post_id, title=row['title'], company='安克创新',
                    location=location, salary=None,
                    url=CAREER + '/larkJobDetail/?websiteId=' + WEBSITE + '&jobId=' + post_id,
                    application_url='https://anker-in.jobs.feishu.cn/index/resume/' + post_id + '/apply',
                    jd=description + ('\n\n任职要求\n' + requirements if requirements else ''),
                    requirements_text=requirements, published_at=None,
                    collected_at=datetime.now(timezone.utc).isoformat(),
                    status='open' if row.get('job_active_status') == 1 else 'unverified',
                    raw=dict(detail_url=url, detail=response, published_at_note='接口 create_time 为创建时间，未视作发布时间'))

    def probe_execution(self, job):
        post_id = platform_id(job.get('platform_id', ''))
        fresh = self.detail(post_id)
        return dict(channel='anker', platform_id=post_id, status='requires_browser_check', observed_auth_state='login_required',
                    application_url=fresh['application_url'], job_status=fresh['status'],
                    reason='真实浏览器只读验证：投递页跳转到手机号/验证码登录；账号、隐私声明和后续必填题需用户处理。未输入、上传或提交。',
                    verification='2026-10-16 browser read-only; historical observation, current login state must be checked by executor',
                    capabilities=dict(discovery='implemented_live_read_verified', detail='implemented_live_read_verified',
                                      input='implemented_fixture_verified_live_pending', upload='implemented_fixture_verified_live_pending',
                                      submit='implemented_fixture_verified_live_pending', receipt='live_write_unverified'))
