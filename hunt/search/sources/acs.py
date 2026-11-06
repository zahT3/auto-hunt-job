"""Validate an offline ACS handoff and build a job without importing or submitting it."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from ...base import now
from ...net.network import validate_url

MAX_RESULT_BYTES = 12_000_000
MAX_HTML_BYTES = 5_000_000


def read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('输入文件超过本地接入大小限制')
    return raw


def compact(text):
    return re.sub(r'\s+', '', text).casefold()


def selected_text(value, body, label, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f'{label}需要是从原文核对的短文本')
    value = value.strip()
    if compact(value) not in compact(body):
        raise ValueError(f'{label}没有出现在 ACS 提取正文中，请核对原文')
    return value


def build_job(result_path, html_path, *, title, company, location=None, fetched_at=None):
    """Only explicit files are read; the source.file embedded in ACS JSON is never opened."""
    result = json.loads(read_bounded(result_path, MAX_RESULT_BYTES))
    if not isinstance(result, dict) or type(result.get('schema_version')) is not int or result['schema_version'] != 1:
        raise ValueError('不支持的 ACS 数据版本')
    data, source, quality = (result.get(key) for key in ('data', 'source', 'quality'))
    if not all(isinstance(item, dict) for item in (data, source, quality)):
        raise ValueError('ACS 没有交付可用正文和证据')
    if (result.get('operation') != 'extract' or result.get('execution_status') != 'completed'
            or quality.get('status') != 'checks_passed' or quality.get('kind') != 'article'):
        raise ValueError('ACS 提取未完成或未通过正文基本检查，拒绝导入')
    url = source.get('url')
    validate_url(url)
    body = data.get('content_text')
    if not isinstance(body, str) or not 200 <= len(compact(body)) <= 100000:
        raise ValueError('JD 正文长度不符合接入要求')
    if '\x00' in body:
        raise ValueError('JD 正文包含异常控制字符')
    html = read_bounded(html_path, MAX_HTML_BYTES)
    if hashlib.sha256(html).hexdigest() != source.get('sha256'):
        raise ValueError('原始网页与 ACS 来源哈希不匹配')
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    if body_hash != data.get('content_sha256'):
        raise ValueError('JD 正文哈希不匹配')
    title = selected_text(title, body, '岗位名称')
    company = selected_text(company, body, '公司名称')
    location = selected_text(location, body, '工作地点', required=False)
    if fetched_at is not None:
        timestamp = datetime.fromisoformat(fetched_at)
        if timestamp.tzinfo is None:
            raise ValueError('网页获取时间必须包含时区')
    # Preserve exact query/fragment identity in the stable ID, even if a consumer normalizes its display URL.
    identity = hashlib.sha256(url.encode()).hexdigest()
    return dict(channel='acs', platform_id=identity, title=title, company=company,
                location=location, jd=body, url=url, salary=None, published_at=None,
                application_url=None, status='unverified', collected_at=now(),
                raw=dict(source_kind='acs', source_url=url, source_html_sha256=source['sha256'],
                         content_sha256=body_hash, fetched_at=fetched_at,
                         extracted_at=result.get('created_at'), engine=result.get('engine'),
                         quality=quality, completeness='unknown', fields_selected_from_text=True,
                         limitations=['职位是否仍在招待确认', '正文完整性待核对',
                                      '来源网址不是已验证的申请入口', '薪资和发布时间未知']))
