"""Candidate facts: resume upload, confirmation and direct import; any change makes open jobs stale."""
import base64
import copy
import json
import uuid
from pathlib import Path

from ..base import Error, dumps, now
from ..profile import synthetic_profile
from ..workbench.actions import LOCKED


class CandidateActions:
    """Resume and candidate facts, mixed into the Store."""

    def upload_resume(self, payload):
        from ..intake import analyze_resume
        filename = payload.get('filename')
        encoded = payload.get('content_base64')
        if not isinstance(filename, str) or not filename or len(filename) > 255:
            raise Error('请选择有效的简历文件')
        if not isinstance(encoded, str) or len(encoded) > 14 * 1024 * 1024:
            raise Error('简历文件最大 10 MiB')
        if type(payload.get('synthetic', False)) is not bool:
            raise Error('合成资料标记必须为布尔值')
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise Error('文件编码无效，请重新选择文件') from exc
        if not content or len(content) > 10 * 1024 * 1024:
            raise Error('请选择 10 MiB 以内的非空文件')
        draft = analyze_resume(filename, content, synthetic=payload.get('synthetic', False))
        draft.update(id=uuid.uuid4().hex, created_at=now())
        # Keep the original bytes for local provenance; never expose arbitrary file paths.
        directory = self.root / 'resumes' / draft['id']
        directory.mkdir(parents=True, mode=0o700)
        suffix = Path(filename).suffix.lower()
        original = directory / ('original' + suffix)
        original.write_bytes(content)
        original.chmod(0o600)
        (directory / 'analysis.json').write_text(dumps(draft), encoding='utf-8')
        (directory / 'analysis.json').chmod(0o600)
        with self.tx() as c:
            self.setmeta(c, 'candidate_draft', draft)
        return self.state()

    def confirm_resume(self, payload):
        ids = payload.get('confirmed_fact_ids', [])
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
            raise Error('请核对并选择要用于本地匹配的事实')
        with self.tx() as c:
            draft = self.meta(c, 'candidate_draft')
            if not draft or draft.get('id') != payload.get('draft_id'):
                raise Error('简历版本已变化，请刷新并核对新版本')
            if draft.get('status') in ('needs_ocr', 'error', 'failed'):
                raise Error('简历尚未成功提取文字，请先处理解析提示')
            candidate = copy.deepcopy(draft['candidate'])
            if set(ids) - {f['id'] for f in candidate['facts']}:
                raise Error('所选事实不属于这份简历')
            for fact in candidate['facts']:
                fact['status'] = 'confirmed' if fact['id'] in ids else 'unconfirmed'
                fact['disclosure'] = 'private'
            candidate['version'] = int(self.meta(c, 'candidate').get('version', 0)) + 1
            self.setmeta(c, 'candidate', candidate)
            self.setmeta(c, 'candidate_draft', None)
            self.intervene(c, '核对上传简历，用于本地画像与匹配；未授权任何对外申请')
            # Persist a clear stale state, rather than presenting old recommendations as current.
            for row in c.execute('SELECT data FROM jobs').fetchall():
                job = json.loads(row[0])
                if job['status'] not in LOCKED | {'rejected'}:
                    job.update(status='new', package=None, approval=None, match=None, recommendation=None, next_action='候选资料已更新，运行搜索或重新准备以更新匹配')
                    self.save(c, job)

    def import_candidate(self, candidate):
        if not isinstance(candidate,dict) or not isinstance(candidate.get('facts'),list): raise Error('候选资料需包含 facts 数组')
        ids=set()
        for f in candidate['facts']:
            if not isinstance(f,dict) or not all(k in f for k in ('id','text','source','status','version','disclosure')) or not isinstance(f['id'],str) or f['id'] in ids or not isinstance(f['source'],dict): raise Error('事实需唯一 ID、原文、来源、状态、版本和披露范围')
            if f['source'].get('kind')=='generated' or f['source'].get('kind')=='draft': raise Error('生成草稿不能作为事实源')
            ids.add(f['id'])
        if synthetic_profile(candidate):
            candidate['synthetic']=True
        with self.tx() as c:
            candidate['version']=int(self.meta(c,'candidate').get('version',0))+1
            self.setmeta(c,'candidate',candidate);self.intervene(c,'本地导入候选事实')
            for row in c.execute('SELECT data FROM jobs').fetchall():
                job=json.loads(row[0])
                if job['status'] not in LOCKED | {'rejected'}:
                    job.update(status='new',package=None,approval=None,match=None,recommendation=None,next_action='候选资料已更新，需重新准备和审核')
                    self.save(c,job)
