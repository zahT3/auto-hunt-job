"""Model-service settings, key hint and consent on a Store; the key itself never leaves llm."""
from . import llm
from ..net import network
from ..base import Error, now


class AiSettings:
    """Model settings and consent, mixed into the Store."""

    def _ai(self, c):
        settings, consent = llm.load_settings(self.root), self.meta(c, 'ai_consent')
        stored_host = llm.key_host(self.root)
        hint = llm.key_hint(self.root) if llm.load_key(self.root, llm.host(settings)) else None
        current = any(llm.consent_ok(consent, settings, k) for k in llm.KINDS)
        # Not the key: only its last four characters ever leave this module.
        return dict(settings=settings, key_hint=hint, key_host=stored_host, key_mismatch=bool(stored_host and not hint), consent=consent, consent_current=current,
                    active=bool(hint and current))

    def ai_settings(self):
        with self.tx() as c:
            return self._ai(c)

    def save_ai_settings(self, payload):
        data = {k: payload[k] for k in llm.DEFAULTS if k in payload}
        try:
            settings = llm.clean_settings(dict(llm.load_settings(self.root), **data))
            key = payload.get('api_key')
            if key is not None and not isinstance(key, str): raise ValueError('密钥格式无效')
            if key and key.strip() and not network.BEARER.fullmatch(key.strip()): raise ValueError('密钥格式无效')
            # Settings first: a failing key write then leaves the old key bound to its old host, which is inert.
            llm.save_settings(self.root, settings)
            if key and key.strip(): llm.save_key(self.root, key, llm.host(settings))
        except ValueError as e: raise Error(str(e)) from None
        except OSError: raise Error('无法写入模型设置或密钥，请检查数据目录权限') from None
        with self.tx() as c: self.intervene(c, '更新模型服务设置')
        return self.ai_settings()

    def grant_ai_consent(self, payload):
        kinds = payload.get('kinds')
        if not isinstance(kinds, list) or not kinds or any(k not in llm.KINDS for k in kinds):
            raise Error('请选择要发送给模型服务的内容类别')
        settings = llm.load_settings(self.root)
        # The UI shows host and model when asking; a stale page must not grant consent for a different pair.
        if payload.get('host', llm.host(settings)) != llm.host(settings) or payload.get('model', settings['model']) != settings['model']:
            raise Error('模型服务或模型已变化，请刷新后重新确认')
        consent = dict(host=llm.host(settings), model=settings['model'], kinds=[k for k in llm.KINDS if k in kinds], granted_at=now())
        with self.tx() as c:
            self.setmeta(c, 'ai_consent', consent); self.intervene(c, '同意向模型服务发送所选内容')
        return self.ai_settings()

    def revoke_ai_consent(self):
        with self.tx() as c:
            self.setmeta(c, 'ai_consent', None); self.intervene(c, '撤销模型服务同意')
        return self.ai_settings()
