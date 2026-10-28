"""Bounded client for an OpenAI-compatible chat API: settings, API key, consent and spend meter.

The key lives only in <data>/secrets.json (0600). It is never part of settings, Store.state(), logs or errors.
Every call goes through network.fetch(bearer=...), the one channel that may send Authorization.
"""
import json
import math
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from . import network

DEFAULTS = dict(base_url='https://api.deepseek.com', model='deepseek-v4-flash',
                price_in=1.0, price_out=2.0, budget_cny=5.0)  # CNY per million tokens; budget per run
KINDS = ('resume_redacted', 'resume_full', 'job_text')
SETTINGS_FILE, SECRETS_FILE = 'ai_settings.json', 'secrets.json'
MODEL = re.compile(r'[A-Za-z0-9._:/\-]{1,100}')
# Reasoning models (deepseek-v4-flash among them) count their hidden thinking as completion tokens: a call that leaves
# room only for its answer gets cut off mid-JSON. Every call gets this much extra room, included in the worst case.
REASONING_ALLOWANCE = 4000


class LLMError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _write_private(path, text):
    # Create the temp file 0600 from the start so the key is never briefly world-readable.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def clean_settings(data):
    """Validate user-supplied settings; returns a new dict or raises ValueError (Chinese message)."""
    merged = dict(DEFAULTS, **{k: v for k, v in (data or {}).items() if k in DEFAULTS})
    base = merged['base_url']
    if not isinstance(base, str):
        raise ValueError('服务地址无效')
    base = base.strip().rstrip('/')
    p, _ = network.validate_url(base)  # HTTPS, public host, no credentials
    if p.query or p.fragment:
        raise ValueError('服务地址不能带查询参数或片段')
    if not isinstance(merged['model'], str) or not MODEL.fullmatch(merged['model'].strip()):
        raise ValueError('模型名无效')
    out = dict(base_url=base, model=merged['model'].strip())
    for key, high in (('price_in', 1000), ('price_out', 1000), ('budget_cny', 100)):
        v = merged[key]
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError('价格与预算必须是数字')
        try:
            v = float(v)
        except ValueError:
            raise ValueError('价格与预算必须是数字') from None
        if not math.isfinite(v) or not 0 <= v <= high:
            raise ValueError('价目须在 0–1000 元/百万 token，预算须在 0–100 元')
        out[key] = v
    return out


def load_settings(root):
    try:
        return clean_settings(json.loads((Path(root) / SETTINGS_FILE).read_text(encoding='utf-8')))
    except (OSError, ValueError):  # missing or damaged file: fall back to the documented defaults
        return dict(DEFAULTS)


def save_settings(root, data):
    settings = clean_settings(data)
    _write_private(Path(root) / SETTINGS_FILE, json.dumps(settings, ensure_ascii=False, indent=2))
    return settings


def host(settings):
    return (urlsplit(settings['base_url']).hostname or '').lower()


def save_key(root, key, host_name):
    """The key is stored with the host it was entered for; it is never sent anywhere else."""
    if not isinstance(key, str) or not network.BEARER.fullmatch(key.strip()):
        raise ValueError('密钥格式无效（8–512 位字母、数字、点、下划线、横线）')
    _write_private(Path(root) / SECRETS_FILE, json.dumps(dict(api_key=key.strip(), host=host_name)))


def _read_secrets(root):
    try:
        data = json.loads((Path(root) / SECRETS_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def key_host(root):
    data = _read_secrets(root)
    return data['host'] if isinstance(data.get('host'), str) and data.get('api_key') else None


def load_key(root, host_name):
    """None when no key is saved or it was entered for another host (a legacy file without host counts as other)."""
    data = _read_secrets(root)
    key = data.get('api_key')
    if not (isinstance(key, str) and network.BEARER.fullmatch(key)) or data.get('host') != host_name:
        return None
    return key


def key_hint(root):
    key = _read_secrets(root).get('api_key')
    return key[-4:] if isinstance(key, str) and network.BEARER.fullmatch(key) else None


def consent_ok(consent, settings, kind):
    """Consent is bound to host + model + content kind; changing either host or model voids it."""
    return (isinstance(consent, dict) and consent.get('host') == host(settings)
            and consent.get('model') == settings['model'] and kind in (consent.get('kinds') or []))


class Meter:
    """Spend estimate in CNY from the price list. Reaching the budget stops further calls."""
    def __init__(self, budget_cny, price_in, price_out):
        self.budget_cny, self.price_in, self.price_out = budget_cny, price_in, price_out
        self.prompt_tokens = self.completion_tokens = 0
        self.estimated = False

    def charge(self, prompt_tokens, completion_tokens, estimated=False):
        self.prompt_tokens += max(0, int(prompt_tokens))
        self.completion_tokens += max(0, int(completion_tokens))
        self.estimated = self.estimated or estimated

    def estimate(self, prompt_chars, completion_chars):
        """When the API reports no usage: about 1.5 characters per token (rough, mixed Chinese/English)."""
        self.charge(math.ceil(prompt_chars / 1.5), math.ceil(completion_chars / 1.5), estimated=True)

    @property
    def spent(self):
        return (self.prompt_tokens * self.price_in + self.completion_tokens * self.price_out) / 1e6

    def projected(self, prompt_chars, max_tokens):
        """Spent so far plus the worst case of one more call (estimated prompt, full max_tokens reply)."""
        return self.spent + (math.ceil(prompt_chars / 1.5) * self.price_in + max_tokens * self.price_out) / 1e6

    @property
    def exhausted(self):
        return self.spent >= self.budget_cny


def _scrub(text, key):
    return str(text).replace(key, '***') if key else str(text)


def chat_json(settings, key, messages, schema_keys, meter, transport=network.fetch, max_tokens=2000):
    """One JSON-mode chat completion. Raises LLMError('budget'|'fetch_error'|'bad_output', ...)."""
    if not key:
        raise LLMError('no_key', '未保存当前服务主机的 API key（换服务地址后需要重新输入）')
    if meter.exhausted:
        raise LLMError('budget', '已达本轮模型花费上限，不再调用模型')
    prompt_chars = sum(len(str(m.get('content', ''))) for m in messages)
    max_tokens = max_tokens + REASONING_ALLOWANCE
    if meter.projected(prompt_chars, max_tokens) > meter.budget_cny:
        raise LLMError('budget', '这次调用的最坏花费会超过本轮上限，不再调用模型')
    body = json.dumps(dict(model=settings['model'], messages=messages, max_tokens=max_tokens,
                           response_format={'type': 'json_object'}), ensure_ascii=False).encode('utf-8')
    try:
        raw = transport(settings['base_url'].rstrip('/') + '/chat/completions', method='POST', data=body,
                        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                        bearer=key, timeout=120)
    except (network.FetchError, ValueError, OSError) as exc:
        raise LLMError('fetch_error', _scrub(exc, key)) from None
    try:
        outer = json.loads(raw)
        content = outer['choices'][0]['message']['content']
        if not isinstance(content, str):
            raise TypeError
    except (ValueError, KeyError, IndexError, TypeError):
        meter.estimate(prompt_chars, len(raw or b''))
        raise LLMError('bad_output', '模型服务返回了无法识别的响应') from None
    usage = outer.get('usage') if isinstance(outer, dict) else None
    pt, ct = (usage.get('prompt_tokens'), usage.get('completion_tokens')) if isinstance(usage, dict) else (None, None)
    if isinstance(pt, int) and isinstance(ct, int) and not isinstance(pt, bool) and not isinstance(ct, bool):
        meter.charge(pt, ct)
    else:
        meter.estimate(prompt_chars, len(content))
    if outer['choices'][0].get('finish_reason') == 'length':
        raise LLMError('bad_output', '模型输出被截断（输出上限不够；推理型模型的思考也计入上限）')
    try:
        result = json.loads(content)
    except ValueError:
        raise LLMError('bad_output', '模型输出不是 JSON') from None
    if not isinstance(result, dict):
        raise LLMError('bad_output', '模型输出不是 JSON 对象')
    missing = [k for k in schema_keys if k not in result]
    if missing:
        raise LLMError('bad_output', '模型输出缺少字段：' + '、'.join(missing))
    return result
