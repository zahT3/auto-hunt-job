"""The search use case: one run of discovery, import, preparation and classification."""
import copy
import threading
import uuid

from ..base import Error, dumps, now
from ..profile import build_profile, synthetic_profile
from ..workbench.actions import LOCKED


class SearchRun:
    """Start and run a search round, mixed into the Store."""

    def start_run(self, demo=False):
        with self.start_lock:
            if self.run_lock.locked() or self.search_thread and self.search_thread.is_alive():
                raise Error('本轮已在运行')
            if not self.is_running():
                raise Error('活动已暂停或停止，先恢复再运行')
            if not demo: self.search_config()
            self.search_thread = threading.Thread(target=self.run, kwargs={'demo': demo}, daemon=True)
            self.search_thread.start()

    def search_config(self):
        """Config for a real search: explicit keywords win, else the orientation's terms; neither is an error (no built-in default terms)."""
        with self.tx() as c:
            cfg, orientation = self.meta(c, 'config'), self.meta(c, 'orientation')
        if self.channel is not None or cfg.get('keywords') or cfg.get('search_terms') or cfg.get('keyword'):
            return cfg
        terms = (orientation or {}).get('terms')
        if not terms: raise Error('请先确定方向或填写关键词')
        return dict(cfg, keywords=list(terms))

    def run(self, demo=False):
        search = None if demo else self.search_config()  # raises before the lock; reused below
        if not self.run_lock.acquire(False):
            raise Error('本轮已在运行')
        run = dict(id=uuid.uuid4().hex, started_at=now(), kind='fixture' if demo else 'real_discovery', discovered=0,
                   duplicates=0, imported=0, prepared=0, applicable=0, verified_submissions=0, failures=[], status='running', user_interventions=0)
        try:
            with self.tx() as c:
                cfg = self.meta(c, 'config')
                candidate = self.meta(c, 'candidate')
                if self.meta(c, 'control') != 'running':
                    raise Error('活动已暂停或停止，先恢复再运行')
            if demo:
                if not self.is_demo:
                    raise Error('合成夹具仅允许在独立 --demo 数据目录运行')
                items = [dict(title='Python 数据工具工程师（合成夹具）',company='合成示例公司',location='深圳',jd='使用 Python 编写数据处理脚本。\n至少 3 年相关开发经验。\n熟悉 Kubernetes。',channel='fixture',platform_id='fixture-python',status='fixture')]
            else:
                with self.tx() as c:
                    c.execute('INSERT INTO runs VALUES(?,?)', (run['id'], dumps(run)))
                if self.channel is not None:
                    items = self.channel.discover(limit=min(cfg['max_jobs'], 5), keyword=cfg['keyword'])
                    if getattr(self.channel, 'last_discovery', None):
                        run['discovery'] = self.channel.last_discovery
                else:
                    from ..discovery import discover
                    cfg = search
                    def source_progress(report):
                        run.setdefault('sources', []).append(copy.deepcopy(report))
                        with self.tx() as connection:
                            connection.execute('UPDATE runs SET data=? WHERE id=?', (dumps(run), run['id']))
                    if cfg.get('sweep') is True and 'discovery_sources' not in cfg:
                        from .. import companies
                        from ..search.query import search_terms
                        try:
                            with self.tx() as c: extra = companies.encountered(c)
                        except (ValueError, TypeError): extra = []
                        cfg = dict(cfg, discovery_sources=companies.select(search_terms(cfg), cfg.get('sweep_max_companies', 300), extra,
                                                                           families=self.chosen_families()))
                    def known(item):
                        # The identity import_job uses for discovered jobs, which always carry platform_id.
                        if not item.get('platform_id'): return False
                        with self.tx() as c:
                            return c.execute('SELECT 1 FROM jobs WHERE identity=?', (item.get('channel', 'import') + ':' + str(item['platform_id']),)).fetchone() is not None
                    result = discover(cfg, profile=build_profile(candidate, confirmed_only=True),
                                      should_continue=self.is_running, browser_profile_root=self.root / 'browser-search',
                                      on_source=source_progress, known=known)
                    items = result['jobs']
                    run['sources'] = result.get('sources', [])
                    run['queries'] = result.get('queries', [])
                    run['expanded_terms'] = result.get('expanded_terms', {})
                    if result.get('entry_check'): run['entry_check'] = result['entry_check']
                    if result.get('sweep'):
                        run.update(sweep=result['sweep'], deadline_reached=result.get('deadline_reached', False))
                    run['coverage_note'] = result.get('coverage_note', '仅覆盖本轮已配置来源与请求预算，不代表全网完整结果')
            if not self.is_running():
                with self.tx() as c:
                    run['status'] = self.meta(c, 'control')
            run['discovered'] = len(items)
            sweep = run.get('sweep')
            # A sweep imports everything it found but prepares only the first few new ones, in discovery order;
            # duplicates take no slot, so a recurring sweep still reaches companies it has not seen.
            fresh = 0
            for item in items[:sweep['max_jobs']] if sweep else items[:cfg['max_jobs']]:
                with self.tx() as c:
                    if self.meta(c, 'control') != 'running':
                        run['status'] = self.meta(c, 'control')
                        break
                try:
                    j, duplicate = self.import_job(item)
                    run['duplicates'] += int(duplicate)
                    run['imported'] += 1
                    slot = not sweep or not duplicate and fresh < sweep['prepare']
                    fresh += int(not duplicate)
                    if slot and j['status'] not in LOCKED | {'rejected', 'approved'}:
                        j = self.prepare(j['id'])
                        run['prepared'] += 1
                        run['applicable'] += int(not j['package'].get('blockers') and not synthetic_profile(candidate) and cfg['targets_confirmed'] and j['channel']=='anker' and not any(x.get('status') == 'not_met' for x in j['match'].get('hard', [])))
                except Exception as e:
                    run['failures'].append(str(e))
            try:
                run.update(self.classify_run())
            except Exception as e:
                run['failures'].append('岗位归类失败：%s' % e)
            if run['status'] == 'running':
                failed_sources = [s for s in run.get('sources', []) if s.get('status') not in ('ok', 'success', 'completed', 'empty', 'filtered_empty') or s.get('truncated')]
                if run.get('deadline_reached'): run['truncated'] = True
                run['status'] = 'partial' if run.get('deadline_reached') else ('partial' if items else 'blocked') if failed_sources else ('empty' if not items else 'completed')
                if run['failures']:
                    run['status'] = 'partial' if run['prepared'] or sweep and run['imported'] else 'failed'
        except Exception as e:
            run.update(status='failed', failures=run['failures'] + [str(e)])
        finally:
            run['finished_at'] = now()
            with self.tx() as c:
                run['user_interventions'] = c.execute('SELECT COUNT(*) FROM interventions WHERE json_extract(data,\'$.time\')>=?',(run['started_at'],)).fetchone()[0]
                c.execute('INSERT OR REPLACE INTO runs VALUES(?,?)', (run['id'], dumps(run)))
            self.run_lock.release()
        return run
