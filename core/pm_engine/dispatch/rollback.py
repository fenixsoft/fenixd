"""rollback.py — R 失败回滚/诊断上报（refactor-giant-classes D1/D3/D5）。

原为 Dispatcher 的 4 个方法（`core/pm_engine/dispatch/_legacy.py`），
原样搬移为 mixin（方法体零改动）。含 2 个 staticmethod：

- `_honest_exit_gap`：测试经 ``Dispatcher._honest_exit_gap`` 类直调
  （`tests/test_honest_exit_convergence.py`），D3 须留类命名空间——mixin 上的
  staticmethod 经继承仍挂在类命名空间；
- `_dispatch_backoffed`：`admin_monitor.py` 生产类直调 `Dispatcher._dispatch_backoffed`
  （D3），同上经继承保留。

跨组协作仍经宿主实例 `self.<method>` / `self._pm.<method>`。
"""

from __future__ import annotations

import shlex
import time
from datetime import datetime, timezone

from core.pm_engine.dispatch.queue import WIP_DEFER_WINDOW_MINUTES, WIP_DEFER_MAX_ROUNDS
from core.state_machine import FROZEN_FIELD


class RRollbackMixin:
    """R 失败回滚/诊断上报（design D1 表 B R 组）。"""

    @staticmethod
    def _honest_exit_gap(pm, spec_name: str, impl_result) -> list:
        """partial 收工的「缺口全部 ⊆ unattainable 申报」判定（诚实退出收敛）。

        返回非空列表 = 缺口确实存在且**每一项**都由结果文件顶层 ``unattainable``
        申报覆盖（如「需用户确认时机后重启 daemon」这类人工运维门控）；空列表 =
        无缺口、或存在未申报缺口、或申报含非法项（防 partial 洗白 / 防非法申报
        部分采信，仍按失败处置）。

        判据单点（fix-redispatch-loop-governance D1/D2b/D4）：收敛判定本体在
        ``core.run_task_track.honest_exit_convergence_gap``（内部即
        ``gap_from_result`` + ``parse_unattainable``），本方法为经 Dispatcher
        命名空间暴露的薄封装（既有调用点与测试经 ``Dispatcher._honest_exit_gap``
        类直调）。缺口口径 MUST 取结果文件，MUST NOT 回退主树 tasks.md 勾选
        （partial 收敛走不到 ``_sync_task_progress`` 回写路径，读主树会把已完成
        任务也算成缺口形成读侧自锁，2026-09-17 事故）。

        与 ``engine._task_completion_blocker`` 的诚实退出分支同判据（同一实现点）。
        判定异常一律返回空（fail-closed 按失败处置）。
        """
        try:
            from core.run_task_track import honest_exit_convergence_gap as _h

            return _h(impl_result or {}, pm.project_root, spec_name)
        except Exception as e:  # noqa: BLE001 — 判定异常按失败处置（不阻断收敛主流程）
            try:
                pm.logger.debug(
                    "pm_engine",
                    f"unattainable 收敛判定异常 '{spec_name}'（按失败处置）: {e}",
                )
            except Exception:
                pass
        return []

    @staticmethod
    def _dispatch_backoffed(spec: dict) -> bool:
        """判断 spec 是否处于派发退避期（派发基础设施失败后防振荡）。

        返回 True 表示本轮不可派发；条目保留在队列中，退避过期后自然恢复，
        配合 periodic full_scan 的 recovery 兜底最多延迟一个扫描周期。

        与 ``queue.py`` ``_dispatch_lock_conflict_pending`` 是对同一字段
        ``_dispatch_backoff_until`` 的同一谓词（未到期→True）的两个落点
        （code-review item aaf6fbb7f6d9）：本侧 staticmethod 按条目 dict 判
        （admin_monitor 类直调 ``Dispatcher._dispatch_backoffed`` 与 engine
        别名复用依赖此签名），queue 侧实例方法按 spec_name 自读状态——本侧
        类级调用点无 pm 实例、无法只读引用对方实现，收敛到单一落点须改
        queue.py（超出本修复边界），故保留双落点并把时间基准写法统一为
        ``time.time()``（与 queue 侧同式，消除表达式漂移）；字段语义或过期
        判定调整时两点 MUST 同步。
        """
        until = spec.get("_dispatch_backoff_until")
        if not until:
            return False
        try:
            return float(until) > time.time()
        except (TypeError, ValueError):
            return False

    def _dispatch_rollback_backoff_seconds(self) -> int:
        """派发异常回滚后的防振荡退避窗（秒）。

        可配 ``pm.dispatch_rollback_backoff_seconds``，默认 300s
        （code-review item 7b281a0886ea：原硬编码 +300 与可配置的
        ``pm.dispatch_backoff_schedule`` 双源不统一，调参/行为诊断困难）。
        非正数/非法值回退缺省；布尔显式拒绝（对齐 repair_lane
        ``_merge_breaker_threshold`` 归一口径）。
        """
        default = 300
        try:
            cfg = self._pm._get_config("pm.dispatch_rollback_backoff_seconds", default)
        except (TypeError, ValueError):
            return default
        # bool 显式拒绝（code-review item f56862fd7372）：float() 把 YAML 布尔
        # true 折算成 1.0，绕过下方非正/NaN/inf 全部守卫，防振荡窗被静默从
        # 缺省 300s 缩成 1s；false 走 v<=0 回退缺省，true/false 行为不对称。
        # 非法值（布尔/无法转数值/NaN/inf/非正数）一律 WARNING 留痕回退缺省
        # （logger getattr 守卫，兼容仅注入 _get_config 的测试替身；与
        # repair_lane _max_retries/_merge_breaker_threshold 的 illegal 分支
        # 同款——code-review item f5024c77c6e3：非布尔非法值此前静默回退
        # 无留痕，调参者无从诊断，与 01c0160765d2 可诊断性口径不一致）。
        if isinstance(cfg, bool):
            logger = getattr(self._pm, "logger", None)
            if logger is not None:
                logger.warning(
                    "pm_engine",
                    "配置 pm.dispatch_rollback_backoff_seconds 非法（布尔不合法），"
                    f"回退缺省 {default}: {cfg!r}",
                )
            return default
        try:
            v = float(cfg)
        except (TypeError, ValueError):
            logger = getattr(self._pm, "logger", None)
            if logger is not None:
                logger.warning(
                    "pm_engine",
                    "配置 pm.dispatch_rollback_backoff_seconds 非法（无法转数值），"
                    f"回退缺省 {default}: {cfg!r}",
                )
            return default
        if v != v or v in (float("inf"), float("-inf")) or v <= 0:
            logger = getattr(self._pm, "logger", None)
            if logger is not None:
                logger.warning(
                    "pm_engine",
                    "配置 pm.dispatch_rollback_backoff_seconds 非法"
                    "（NaN/inf/非正数均不合法），"
                    f"回退缺省 {default}: {cfg!r}",
                )
            return default
        # 亚秒正值下限保护（code-review item 77be0cfcbe43）：int 截断会把
        # 0<v<1 压成 0，退避窗立即过期、防振荡静默失效，故至少保留 1 秒。
        return max(1, int(v))

    def _rollback_frozen_recheck(self, spec_name: str, agent_type: str) -> bool:
        """回滚写盘前的冻结复查（code-review item 030f2c204875）。

        ``_rollback_failed_dispatch`` 开头 read_one 的 status 判态与 update_spec
        落盘之间无原子性：窗口内 spec 被并发 freeze_for_human 冻结时，回滚写会
        落在冻结现场上——冻结剥离（state_machine._apply_updates_entry）只剥
        status 键且 update_spec 仍返回 True，error 写入/清空照常生效、会覆盖
        内嵌「原状态 X」的冻结 error，人工解冻经 parse_orig_status 无法还原
        （f3a8a1249ede/a5e1c9319ad4 系列在其余失败处置站点系统性防护的同型
        并发窗口，本方法此前完全未设防）。本守卫取「先复查冻结标记再写」的
        最小侵入修法（state_machine 无 status 条件写公开原语；applied_out 的
        锁内 _stripped 信号需改 update_spec 调用签名，既有测试桩按
        ``(name, updates)`` 直替不可用）：复查发现 frozen 即放弃回滚写与重派
        入队，冻结现场原样保留待人工解冻。

        Returns: True = 复查发现已冻结，调用方直接返回（不写盘、不入队）。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        if not entry.get(FROZEN_FIELD):
            return False
        self._pm.logger.warning(
            "pm_engine",
            f"Rollback abandoned for '{spec_name}' ({agent_type}): 写盘前复查"
            "发现已冻结——放弃回滚写与重派入队，冻结现场保留待人工解冻还原",
        )
        return True

    def _rollback_write_guarded(
        self, spec_name: str, agent_type: str, updates: dict
    ) -> bool:
        """回滚状态写 + 并发冻结防护 + 返回值核对（code-review item 030f2c204875）。

        三段收口（verifier/implementer 分支共用；两分支写均带 status 键与
        error 清空语义）：

        - 写前复查：``_rollback_frozen_recheck`` 发现 frozen 即放弃整段回滚；
        - update_spec 返回值核对：False = 条目缺失/原子写失败，复位未生效
          （此前返回值未核对，复位失败仍继续入队重派）；
        - 写后复核：写前复查与写锁之间的残余窗口由「frozen 且 error 为 None」
          实锤识别——frozen 条目的 error 恒非 None（freeze_spec/freeze_for_human
          写入必带文案），None 只可能来自本回滚的清空，WARNING 留痕供人工
          核对解冻（原始冻结文案已不可恢复）；frozen 且 error 非空 = 冻结写
          落在回滚写之后、冻结现场完整。

        仅适用带 status 键、error 清空语义的分支；spec-review 分支写不含
        status 键（冻结剥离对它无信号）、error 为非空业务文案（error-None
        判据不成立），只取写前复查（见分支内注释）。

        Returns: True = 回滚写已生效且未检出冻结，调用方继续留痕与重派入队；
        False = 已放弃（写前冻结/写失败/写后检出冻结），调用方直接返回。
        """
        if self._rollback_frozen_recheck(spec_name, agent_type):
            return False
        if not self._pm.state_machine.update_spec(spec_name, updates):
            self._pm.logger.warning(
                "pm_engine",
                f"Rollback write failed for '{spec_name}' ({agent_type}): "
                "update_spec 返回 False（条目缺失/原子写失败），复位未生效"
                "——跳过重派入队",
            )
            return False
        post = self._pm.state_machine.read_one(spec_name) or {}
        if not post.get(FROZEN_FIELD):
            return True
        if post.get("error") is None:
            self._pm.logger.warning(
                "pm_engine",
                f"Rollback raced concurrent freeze for '{spec_name}' "
                f"({agent_type}): status 写被冻结剥离但 error 清空已生效，"
                "冻结 error（内嵌原状态）疑被覆盖——须人工核对解冻还原",
            )
        else:
            self._pm.logger.info(
                "pm_engine",
                f"Rollback applied then frozen for '{spec_name}' "
                f"({agent_type}): 冻结写落在回滚写之后、冻结现场完整"
                "——跳过重派入队",
            )
        return False

    def _rollback_failed_dispatch(self, spec_name: str, agent_type: str, exc: Exception):
        """派发/执行异常时回滚滞留中间态的 spec 到可重试态（fix: 伪 bug 卡死）。

        - implementer 失败：implementing → ready，清空 run 字段；error 置 None 以便
          full_scan 的 spec_ready recovery 再次拾起（错误详情记入 _last_dispatch_error）。
        - verifier 失败：testing → implemented，清 tester_run；error 置 None 以便
          恢复拾取（错误详情记入 _last_dispatch_error，与 implementer 分支同口径）；
          实现保留（不重实现）。
        设置 _dispatch_backoff_until（默认 5 分钟，可配
        ``pm.dispatch_rollback_backoff_seconds``）吸收 inotify 触发的即时重派振荡；
        重试由队列条目 + full_scan recovery 兜底（最长 30 分钟窗口）。
        """
        try:
            spec_entry = self._pm.state_machine.read_one(spec_name)
            if not spec_entry:
                # spec 条目缺失/读取为空（并发删除或状态读取异常，code-review item
                # 729c57c474d7）：不再静默返回——与 01c0160765d2 的可诊断性口径一致，
                # 事后对账可确认回滚被跳过而非未触发。
                self._pm.logger.info(
                    "pm_engine",
                    f"派发失败回滚：spec='{spec_name}' 条目缺失/读取为空 "
                    f"agent_type={agent_type!r}（跳过回滚，仅留痕）",
                )
                return
            status = spec_entry.get("status")
            backoff_until = int(datetime.now(timezone.utc).timestamp()) + (
                self._dispatch_rollback_backoff_seconds()
            )
            if agent_type == "verifier" and status == "testing":
                # error 置 None（code-review item 5d15a55cbce8，与 implementer
                # 分支同口径）：非空 error 对 implemented 态恢复/展示路径是额外
                # 噪声源，失败详情改记结构化字段 _last_dispatch_error，两条回滚
                # 车道对 error 字段语义一致。
                # 并发冻结防护与返回值核对收口到 _rollback_write_guarded
                # （code-review item 030f2c204875）：判态后直写会把 error: None
                # 落到窗口内并发的冻结现场上（冻结剥离只剥 status 键），覆盖
                # 内嵌「原状态 X」的冻结 error、破坏人工解冻还原。
                if not self._rollback_write_guarded(
                    spec_name,
                    agent_type,
                    {
                        "status": "implemented",
                        "tester_run": None,
                        "error": None,
                        "_last_dispatch_error": f"Verification dispatch failed (retryable): {exc}",
                        "_dispatch_backoff_until": backoff_until,
                    },
                ):
                    return
                self._pm.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' testing → implemented (verifier never started): {exc}",
                )
                # 重入队前先幂等摘除本 spec 的 verify 单飞登记（code-review item
                # 056f6fb5e7d7）：本方法在 worker 的 except 段被同步调用，登记
                # 仍在其出队分流内置位、要到 worker finally 才摘除（queue.py），
                # 此窗口内 _enqueue 的单飞守卫必然拒绝重入队——docstring 承诺的
                # 「队列条目 + full_scan recovery」两腿中前者结构性恒不生效，
                # 且每次留下误导性守卫 WARNING（backoff.py 的 infra-retry 定时器
                # 已用延迟盖窗规避同型交互，本同步路径改用先摘除）。摘除语义=
                # 与 worker finally 的 discard 合并（finally 再摘为幂等 no-op）：
                # 异常路径上原验证 run 已终止，摘除到新条目真正出队之间不存在
                # 双在飞——新条目出队另受 _dispatch_entry_ready 状态守卫与
                # _dispatch_backoffed 退避门把关（退避期内条目保留队列不丢）。
                # getattr 兼容仅注入部分属性的测试替身；锁段与登记/摘除既有
                # 纪律一致（_queue_lock 为 RLock，本方法无调用方持该锁）。
                _active_verifies = getattr(self, "_active_verifies", None)
                if _active_verifies is not None:
                    with self._queue_lock:
                        _active_verifies.discard(spec_name)
                # 入队独立守卫（code-review item 01bfb767effe，与 implementer 分支
                # 同款）：_enqueue 若裸露在大 try 内，队列写入抛错（锁/IO）会跳到
                # 外层 except 记误导性「State rollback failed」（尽管上方 update_spec
                # 已把 spec 复位 implemented）且重派条目静默丢失。单独守卫：失败
                # 如实记 ERROR，不覆盖状态复位成果（full_scan recovery 兜底）。
                try:
                    self._enqueue(spec_name, "verifier")
                except Exception as enqueue_exc:  # noqa: BLE001 —— 入队失败不吞回滚成果
                    self._pm.logger.error(
                        "pm_engine",
                        f"Redispatch enqueue failed for '{spec_name}' "
                        f"(state rolled back to implemented, pending full_scan "
                        f"recovery): {type(enqueue_exc).__name__}: {enqueue_exc}",
                    )
            elif agent_type == "spec-review" and status == "reviewing":
                # 评审 worker 异常回滚（fix-spec-review-blocking-dispatch 1.8
                # 双保险）：四步链之外异常（构造失败/快照路径异常）时 spec 可能
                # 停在 reviewing 且 reviewer_run 未被推进——清锚点、保持
                # reviewing。MUST NOT 在此处重新入队：_run_spec_review_worker
                # 已在四步链外异常路径显式入队（tasks 1.8），此处作为
                # defense-in-depth 兜底仅清理状态，避免双入队导致无限重派
                # （worker 异常 → 入队 → 再 worker 异常 → 再入队…）。
                # 未入队的残余场景由 recovery 的 reviewing 分支兜底拾取。
                # 派发退避与另两条回滚车道同口径（code-review item
                # 9d6d6fc2cbf4）：reviewing 的恢复链（recovery 重触发
                # spec_reviewing → _enqueue → _process_queue）同样经
                # _dispatch_backoffed 门——缺退避字段该门恒放行，构造失败/
                # 快照路径异常这类常确定性复现的派发异常会按恢复扫描节奏
                # 无节流 rollback→重触发循环。条目退避期内留队列、过期自然
                # 恢复（_dispatch_backoffed 既有语义）。
                # 并发冻结防护（code-review item 030f2c204875）：本分支写不含
                # status 键——冻结剥离对它无信号（error/reviewer_run 会照常
                # 生效，覆盖冻结 error 与冻结时保全的 reviewer_run 锚点），写后
                # 复核的 error-None 判据亦不成立（本分支 error 为非空业务
                # 文案），故只取写前复查：发现冻结即放弃整段写，残余竞态窗口
                # 收敛到复查读与写锁之间。
                if self._rollback_frozen_recheck(spec_name, agent_type):
                    return
                # 返回值核对（code-review item 90b4004274a9，与 verifier/
                # implementer 分支 _rollback_write_guarded 内的返回值核对段
                # 同口径）：False = 条目缺失/原子写失败，reviewer_run/error
                # 均未落盘——不记成功回滚文案，改记「复位未生效」WARNING。
                # 本分支写不含 status 键、error 为非空业务文案，不能走
                # _rollback_write_guarded 的写后复核，故只 inline 返回值核对；
                # 状态保持 reviewing，恢复仍由 recovery 的 reviewing 分支兜底。
                if not self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "reviewer_run": None,
                        "error": f"spec-review-incomplete: dispatch exception: {exc}",
                        "_dispatch_backoff_until": backoff_until,
                    },
                ):
                    self._pm.logger.warning(
                        "pm_engine",
                        f"Rollback write failed for '{spec_name}' ({agent_type}): "
                        "update_spec 返回 False（条目缺失/原子写失败），复位未生效"
                        "（reviewing 恢复仍由 recovery 兜底）",
                    )
                    return
                self._pm.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' reviewing（评审 worker 异常，"
                    f"清理锚点待恢复拾取）: {exc}",
                )
            elif agent_type in ("implementer", "fast-track") and status == "implementing":
                # 死亡 run 豁免（fix-budget-counting-semantics D1）：异常路径＝
                # run 无收工结果产出（进程消失/零输出/网关链路耗尽），回退本次
                # 启动的预算计数。计数在 worker 启动处先行递增，此处补偿回退。
                # run_reason 传入 exc 信息（派发异常不属监督超时/停滞，应豁免）。
                #
                # 隔离（code-review item a986aab6fa9d）：豁免是**尽力而为的记账**
                # （bump_impl_budget / bump_budget_exempt_runs 均写状态文件），若它
                # 自己抛异常（状态文件锁/IO、_impl_run_budget_used 读取失败），
                # 控制流会直接跳到外层 except，使下面的
                # update_spec(→ready)/_last_dispatch_error/_enqueue **永远执行不到**
                # ——spec 卡在 implementing 且无队列条目，正是本方法要修复的故障。
                # 故必须独立 try/except，让豁免失败不能中止回滚。
                # exempt_applied 标记（code-review item 6d56aa5de387）：审计日志
                # 无条件落盘，须携带豁免是否实际生效，否则记账失败（状态文件
                # 锁/IO 异常）时对账会把未生效的豁免当作已豁免。
                # 结果判定（code-review item 963d40154301）：_exempt_dead_run_budget
                # 对拒绝/幂等跳过/记账异常三条未生效路径均静默 return、不抛异常，
                # 仅凭本处 except 判不出未生效——改按其返回指纹置标记，并把指纹
                # 附进审计行，供与 budget.py 内部拒绝/跳过 WARNING/INFO 交叉对账。
                exempt_applied = False
                exempt_result = None
                try:
                    exempt_result = self._pm._exempt_dead_run_budget(
                        spec_name,
                        f"dispatch exception: {str(exc)[:80]}",
                        run_reason=str(exc) if exc else None,
                    )
                    exempt_applied = exempt_result == "applied"
                except Exception as exempt_exc:  # noqa: BLE001 —— 记账失败不阻塞回滚
                    self._pm.logger.warning(
                        "pm_engine",
                        f"budget exempt failed for '{spec_name}'（按未豁免继续回滚）: "
                        f"{type(exempt_exc).__name__}: {exempt_exc}",
                    )
                self._pm.logger.info(
                    "pm_engine",
                    f"budget_exempt_audit: spec={spec_name}, "
                    f"dispatch_exception, exempt_applied={exempt_applied}, "
                    f"exempt_result={exempt_result}, "
                    f"exc={str(exc)[:120]}, "
                    f"run_reason={str(exc)[:80] if exc else ''}",
                )
                # fix-run-hang-amplification 2.5：update_spec 增量更新——此处只清
                # error 与 run 字段，_impl_diagnosis 结构化诊断 MUST NOT 被清除
                # （重派 attempt 需继承上轮诊断）。
                # （fix-fasttrack-recovery-resume D5 区分注释）本处清锚点属**有意回滚**
                # ——run **从未启动**（dispatch 异常），`_recovery_resume` 尚未被消费、
                # 锚点亦非本轮产出。MUST NOT 消费该标记（保持原值），使其在原样重派
                # 时仍可被 dispatch 入口消费；清 implementer_run 只是剥除从未启动的
                # run 留下的空壳字段。
                # branch 条件清空（code-review item 95108482c6c5）：branch 是续做
                # 锚点链的一环——queue.py 两条派发分支（implementer/fast-track）
                # 均按 `branch if _recovery_resume else None` 解析续做载体 pre_wt。
                # 本轮若是 recovery 续做重派（标记待消费 + branch 指向上一轮保留
                # 分支），且异常发生在标记消费之前（ensure_spec_committed/预算
                # 计数/载体解析均在续做判定前执行，抛错即入本回滚），无条件清
                # branch 会让下轮消费侧取到 pre_wt=None，静默退化成全新 worktree
                # 派发、保留分支脱锚。故与 fast_track._downgrade_fast_track_scale
                # 的 D4 口径一致：标记在位时 MUST NOT 清空 branch（载体缺失/不可用
                # 时消费侧 resolve_resume_site 自会降级为全新派发，保留无副作用）；
                # 无标记时 branch 属上一轮空壳/陈旧锚点，照常清除。
                resume_pending = bool(spec_entry.get("_recovery_resume"))
                rollback_updates = {
                    "status": "ready",
                    "implementer_run": None,
                    "tester_run": None,
                    "error": None,
                    "_last_dispatch_error": f"Implementation dispatch failed (retryable): {exc}",
                    "_dispatch_backoff_until": backoff_until,
                }
                if not resume_pending:
                    rollback_updates["branch"] = None
                # 并发冻结防护与返回值核对收口到 _rollback_write_guarded
                # （code-review item 030f2c204875，verifier 分支同款）：判态与
                # 写盘之间隔着预算豁免记账等 I/O，窗口内并发的冻结现场会被
                # error: None 与锚点清空覆盖，破坏人工解冻还原。
                if not self._rollback_write_guarded(
                    spec_name, agent_type, rollback_updates
                ):
                    return
                self._pm.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' implementing → ready "
                    f"({agent_type} never started): {exc}",
                )
                # 入队独立守卫（code-review item 9842741702fe）：_enqueue 原在大
                # try 内任何守卫外——队列写入抛错（锁/IO）会跳到外层 except 记
                # 误导性「State rollback failed」（尽管上方 update_spec 已把 spec
                # 复位 ready）且重派条目静默丢失，正是本方法要修复的卡死状态
                # （只剩 full_scan recovery 兜底）。单独守卫：失败如实记 ERROR，
                # 不覆盖状态复位成果。
                try:
                    self._enqueue(spec_name, agent_type)
                except Exception as enqueue_exc:  # noqa: BLE001 —— 入队失败不吞回滚成果
                    self._pm.logger.error(
                        "pm_engine",
                        f"Redispatch enqueue failed for '{spec_name}' "
                        f"(state rolled back to ready, pending full_scan "
                        f"recovery): {type(enqueue_exc).__name__}: {enqueue_exc}",
                    )
            else:
                # 未覆盖 (agent_type, status) 组合（code-review item 01c0160765d2）：
                # 旧 if/elif 链无兜底——静默返回、无日志、无回滚，残余卡死形态在
                # 日志里不可诊断。至少记一条 WARNING 暴露观测到的组合。
                self._pm.logger.warning(
                    "pm_engine",
                    f"派发失败回滚：未覆盖组合 spec='{spec_name}' "
                    f"agent_type={agent_type!r} status={status!r}（无回滚动作，仅留痕）",
                )
        except Exception as e2:
            self._pm.logger.error("pm_engine", f"State rollback failed for '{spec_name}': {e2}")

    def _emit_mergeback_alert(
        self,
        spec_name: str,
        signal_type: str,
        state_updates,
        state_fail_note: str,
        error_note: str,
        description: str,
        evidence_obj,
        recommended_action: str,
    ) -> None:
        """merge-back/stash 上报统一骨架（code-review item 2f7cef6b18a6）。

        四个上报站点（``_report_stash_pop_conflict`` /
        ``_report_mergeback_wip_overlap`` /
        ``_report_mergeback_spec_dir_inflight_stuck`` /
        ``_report_mergeback_wip_defer_stuck``）原各自复制粘贴的「状态写入 +
        ERROR 日志 + admin_store 告警」三段脚手架收敛于此，行为零变化：
        差异化文案（signal_type/description/recommended_action/两段日志文本）
        与 evidence 字典由站点逐字传入。

        - 状态写入：update_spec 落站点给定的字段集（state_updates 亦可为
          零参 callable——需读状态做记账的站点把构造收进同一兜底，保证
          「构造失败与写入失败同路 WARNING 不阻塞」）；失败仅记 WARNING
          （state_fail_note + 异常）。
        - logger.error 按 error_note 留痕（无论状态写入成败）。
        - admin 告警直发：evidence 一律先经 ``_str_field``（实现在
          core/agent_runner/prompt_builder.py）序列化为 str 再入 record
          （dict 穿透 ``str.replace`` 会致 Administrator 唤起失败，
          fix-alert-evidence-render-crash 先例）后经 ``AdminStore.append``
          发 major 告警；任何异常仅记 WARNING（非阻塞），不阻断
          merge-back 主流程。
        """
        try:
            updates = state_updates() if callable(state_updates) else state_updates
            self._pm.state_machine.update_spec(spec_name, updates)
        except Exception as e:
            self._pm.logger.warning("pm_engine", f"{state_fail_note}: {e}")
        self._pm.logger.error("pm_engine", error_note)
        try:
            from core.agent_runner.prompt_builder import _str_field
            from core.admin_store import AdminStore, SIGNAL

            evidence = _str_field(evidence_obj)
            store = AdminStore(self._pm.project_root, self._pm.logger)
            written = store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": signal_type,
                    "spec": spec_name,
                    "severity": "major",
                    "description": description,
                    "evidence": evidence,
                    "recommended_action": recommended_action,
                }
            )
            if written is None:
                # 下限保护拒写（code-review item 503dc872568f）：append 返回
                # None＝记录未落盘，按「告警写入失败（非阻塞）」既有分支同
                # 口径记 WARNING，不得伪造「已写入」成功日志误导事后对账。
                self._pm.logger.warning(
                    "pm_engine",
                    f"{signal_type} 告警未落盘 '{spec_name}'"
                    f"（admin store 下限保护拒写，非阻塞）",
                )
            else:
                self._pm.logger.info(
                    "pm_engine",
                    f"{signal_type} 告警已写入 admin store: '{spec_name}'",
                )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"{signal_type} 告警写入失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _report_stash_pop_conflict(
        self, spec_name: str, conflict_files: list, merge_info=None
    ) -> None:
        """pop 冲突自愈后上报被丢弃的 stash 改动文件清单（fix-stashpop-deadlock）。

        主树已通过 checkout HEAD + reset 自愈回到干净可写状态，merge 结果不丢失、
        状态正常推进到 implemented。上报走双通道（fix-mergeback-stashpop-silent-loss
        D1）：既有 spec.error 字段写入保持不变（向后兼容 dashboard 时间轴读侧）；
        另经 admin_store.append 直发一条 ``signal_type=stash_pop_conflict`` 告警——
        通知不再依赖瞬态 error 字段或日志指纹风暴规则。告警 description 含 spec 名、
        冲突文件清单、stash 条目去向（保留/drop + sha）、逐文件找回命令，以及
        merge-back 前的 WIP 重叠预检清单（若有）。

        error 文本格式（供 dashboard/admin 可读）：``stash pop conflict: files=[...]``
        """
        if not conflict_files:
            return
        msg = f"stash pop conflict: files={conflict_files}"
        # 条目去向从 worktree_manager 读，读取对 _main_tree_lock 短暂加锁
        # （code-review item 82f9406f7516）：该属性是共享实例状态，他 spec 的
        # merge-back 入口会在同把锁内 _reset_stash_state()，无锁读窗口内可把
        # 他 spec 的重置确定态误读为本 spec 条目去向（已 auto-drop 被报成
        # 「保留在栈中」）——与 guard 段写入及入口重置同锁串行后再读。
        # kept 缺键时按 **True** 保守默认
        # （code-review item f09a5bfeb402）：旧实现 `fate.get("kept")` 缺键
        # 回 None（falsy）会误报「已被自动 drop」并写 stash_kept=False，
        # 编造数据丢失声明；缺键与读取失败同属「无法确证 drop」，一律按保留。
        try:
            wm = self._pm.agent_runner.worktree_manager
            with wm._main_tree_lock:
                fate = dict(wm.last_stash_entry_fate)
        except Exception:
            fate = {"kept": True, "sha": ""}
        sha = fate.get("sha", "") or ""
        short_sha = sha[:12] if sha else ""
        if fate.get("kept", True):
            fate_desc = (
                f"stash 条目保留在栈中（栈顶 sha {short_sha}，" f"git stash list 可见）"
                if short_sha
                else "stash 条目保留在栈中"
            )
        else:
            fate_desc = (
                f"stash 版已被合并结果完全取代，条目已自动 drop"
                f"（commit {short_sha}，gc 前可按 sha 找回）"
                if short_sha
                else "stash 条目已被自动 drop"
            )
        recover_cmds = (
            "; ".join(f"git show {sha}:{shlex.quote(f)}" for f in conflict_files)
            if sha
            else "git stash show / git stash list 人工核对"
        )
        overlap = list(getattr(merge_info, "wip_overlap", []) or [])
        overlap_desc = (
            f"；merge-back 前 WIP 重叠预检命中 {len(overlap)} 文件"
            f"（可能与本次丢弃相关）：{overlap}"
            if overlap
            else ""
        )
        description = (
            f"SPEC '{spec_name}' merge-back stash pop 冲突已自愈："
            f"{len(conflict_files)} 个文件的未提交改动被丢弃 "
            f"({', '.join(conflict_files)})。{fate_desc}{overlap_desc}。"
            f"逐文件找回：{recover_cmds}"
        )
        # ERROR 留痕按条目去向分流（code-review item 4eab9c81e3a5）：与上方
        # fate_desc 口径对齐——已自动 drop 的条目不在 stash 栈中（stash show /
        # stash list 均不可见），找回路径是按 sha 逐文件 git show（gc 前有效），
        # 不能沿用「stash 保留」的固定文案误导事后对账与人工找回。
        if fate.get("kept", True):
            error_note = (
                f"'{spec_name}' {msg} —— stash 保留，可用 git stash show 找回被丢弃改动"
            )
        else:
            recover_hint = (
                f"stash 条目已自动 drop，可按 commit {short_sha} 逐文件 "
                f"git show {sha}:<file> 找回被丢弃改动（gc 前有效）"
                if sha
                else "stash 条目已被自动 drop"
            )
            error_note = f"'{spec_name}' {msg} —— {recover_hint}"
        # admin 告警直发（fix-mergeback-stashpop-silent-loss D1）：低频事件、
        # 无风暴风险，不加节流。任何异常都不阻塞 merge-back 主流程。
        self._emit_mergeback_alert(
            spec_name,
            "stash_pop_conflict",
            {"error": msg},
            f"stash pop conflict 上报失败 '{spec_name}'（非阻塞）",
            error_note,
            description,
            {
                "conflict_files": list(conflict_files),
                "stash_kept": bool(fate.get("kept", True)),
                "stash_sha": sha,
                "wip_overlap": overlap,
            },
            (
                "git stash list 查条目去向；按逐文件 git show <sha>:<file> 命令"
                "核对内容，仍需要的改动手动落回工作区；确认零独有内容后 "
                "git stash drop 清理"
            ),
        )

    def _report_mergeback_wip_overlap(
        self, spec_name: str, merge_info, branch: str, merge_error: str
    ) -> None:
        """WIP 重叠闸门阻塞告警直发（evo-merge-back-wip-overlap-gate D1/D3）。

        在 merge 结果处理的**失败/阻塞分支**、``wip_gate_blocked=True`` 时调用
        （主通道与 fast-track 通道两处站点均覆盖）：merge-back 未发生（不 stash、
        不 merge、不 pop，主树零污染），spec 保持 in-flight。告警含 spec 名、
        重叠文件清单、策略（阻塞）、找回命令与处置指引——signal_type=
        ``mergeback_wip_overlap``，经 admin_monitor 白名单摄取唤起 Administrator。

        **序列化加固（D6）**：evidence 一律先经 ``_str_field``（实现在
        core/agent_runner/prompt_builder.py）序列化为 str 再入 record——dict
        穿透 ``str.replace`` 会致 Administrator 唤起失败（fix-alert-evidence-
        render-crash 先例）。

        任何异常都不阻塞 merge 结果处理主流程。
        """
        overlap = list(getattr(merge_info, "wip_overlap", []) or [])
        # 找回/核对指引指向分支本体（code-review item c48bce2fa85e）：本车道
        # 不 stash、不 merge、不 pop，主树零污染——不存在 stash 条目可供
        # 「查条目去向」，也没有改动被丢弃，MUST NOT 整段复制 stash pop
        # 站点的溯源文案把 Administrator 引向不存在的 stash 现场。
        recover_cmds = (
            f"分支 '{branch}' 改动完整保留，git log/git diff 该分支即可核对；"
            f"核对主树重叠改动用 git status/git diff"
        )
        # 处置指引对齐自动 merge-only 重试车道语义（code-review item
        # f64b8009ab7b）：提交/stash 重叠改动后由周期复查消费者自动重试，
        # ready 重派仅在自动重试超限降级后使用。
        description = (
            f"SPEC '{spec_name}' merge-back 被 WIP 重叠闸门阻塞"
            f"（策略=escalate 升级拦截）："
            f"主树 {len(overlap)} 个已跟踪文件存在未提交改动，与分支 "
            f"'{branch}' 的改动路径重叠（{overlap}）——为避免 pop 冲突静默丢弃，"
            f"已中止合并（主树零污染，未 stash/未 merge/未 pop）。"
            f"找回/核对：{recover_cmds}。"
            f"处置指引：提交（git add/commit）或 stash（git stash push）主树这些"
            f"重叠改动后等待即可——周期复查车道会自动 merge-only 重试并续走 "
            f"merge-back，无需 ready 重派；仅当自动重试超限降级为人工处置告警后，"
            f"才需复位 ready 重派或人工完成合并。"
        )

        def _wip_overlap_updates() -> dict:
            # 结构化等待载体（evo-add-wip-defer-merge-retry-consumer 1.1）：
            # error 文本不再作为唯一现场标志——同次 update_spec 增写
            # _wip_gate_deferred=True + 复用 _merge_retry_count/_merge_retry_first_at
            # 记账（与 spec_dir_inflight 顺延共用一套计数，混账已知、接受——
            # 见设计「风险与边界」）。首阻时刻沿用既有值（同一 spec 先后经历
            # 两种阻断时窗口不重置），缺省取当前时刻。消费者（queue.py 周期
            # 复查）据此自动 merge-only 重试；标志的生命周期不变式：
            # implementing+_wip_gate_deferred ⇒ 无在飞实现 run（触发阻断的
            # run 已在结果处理期收尾，新 run 只能自 ready 派发而 boot 两个
            # 复位写点已清标志）。以 callable 传入助手：记账读取与 update_spec
            # 同路兜底（构造失败与写入失败同WARNING，不阻塞后续留痕与告警）。
            entry = self._pm.state_machine.read_one(spec_name) or {}
            count, first_f = self._parse_defer_accounting(entry, time.time())  # 首阻缺省=now，写侧回填与原 int(time.time()) 同口径
            return {
                "error": f"mergeback wip overlap blocked (policy=escalate): files={overlap}",
                "_wip_gate_deferred": True,
                "_merge_retry_count": count,
                "_merge_retry_first_at": int(first_f),
            }

        self._emit_mergeback_alert(
            spec_name,
            "mergeback_wip_overlap",
            _wip_overlap_updates,
            f"mergeback wip overlap 状态上报失败 '{spec_name}'（非阻塞）",
            (
                f"'{spec_name}' mergeback wip overlap blocked —— 主树零污染，"
                f"等待人工提交/stash 重叠改动后重新放行"
            ),
            description,
            {
                "overlap_files": overlap,
                "policy": "escalate",
                "branch": branch,
                "merge_error": str(merge_error),
            },
            (
                "提交或 stash 主树与分支重叠的未提交改动"
                "（git add/commit 或 git stash push）后等待自动 merge-only 重试"
                "（周期复查车道自愈，无需 ready 重派）；仅自动重试超限降级后才需"
                "人工复位 ready 重派或手动完成合并；被收纳/保留的改动可用 "
                "git stash list 与逐文件 git show <sha>:<file> 找回核对"
            ),
        )

    def _report_mergeback_spec_dir_inflight_stuck(
        self, spec_name: str, merge_info, branch: str, merge_error: str,
        retry_count: int, first_at: int, selfheal_evidence: str | None = None,
        cause_label: str = "spec 目录在飞编辑",
    ) -> None:
        """spec 目录在飞编辑顺延超限回落告警（evo-merge-back-spec-dir-inflight-guard D1a/D2）。

        顺延窗口（``mergeback.spec_dir_inflight_grace_minutes``，缺省 30 分钟）或
        连续顺延轮数（``mergeback.spec_dir_inflight_max_rounds``，缺省 3）超限时
        调用：MUST NOT 无限顺延（无上限顺延会把事故中的「整轮重派」换成「永不再
        处理」，比事故更差）。走既有「发告警 + 等待人工处置」直通，对齐
        ``_report_mergeback_wip_overlap`` 同型语义：

        - spec 保持 in-flight（implementing），分支/锚点原样保留（MUST NOT 静默
          丢弃分支）；
        - 写 admin store 信号（signal_type=``mergeback_spec_dir_inflight_stuck``）——
          该 spec 对本窗口的可见性由本告警 + 后续 orphaned_state 探测（implementing
          无活动 run 超短阈值）共同兜底（周期巡检对 ready 态在飞等待不可见，
          故不降级 ready）；
        - 任何异常不阻塞调用方主流程。

        告警描述含找回/处置指引（提交主树 spec 目录后，人工可 reset 复位实现状态
        重新放行，或等待 daemon 恢复通道重试）。

        ``selfheal_evidence``（evo-mergeback-archive-residue-selfheal 1.2）：熔断
        出口前的归档残留自愈评估摘要（判据命中与否、补提交 hash、重放/失败
        原因），非空时增补进告警 description 与 evidence，保持人工可见。

        ``cause_label``（code-review item a9a96d9d650e）：可重试成因的人工可读
        标签（queue.py ``_MERGEBACK_DEFER_CAUSES``）。三类成因（spec 目录在飞
        编辑 / 主树脏 / dispatch 锁冲突）共用本告警站点，description 与处置指引
        不再按「spec 目录在飞编辑」单一成因写死——标签前缀选差异化指引，未识别
        标签回落 spec 目录指引（保守方向：提交 spec 目录对主树脏/锁冲突无害）。
        """
        # 成因差异化处置指引（前缀匹配 queue.py 标签文本，两处文案同源）
        if cause_label.startswith("主树"):
            fix_hint = (
                "处置指引：提交或 stash 主树与分支重叠的未提交改动"
                "（git add/commit 或 git stash push，重叠文件清单见 merge_error），"
                "等待自动 merge-only 重试；或人工复位 ready 重放 merge-back。"
            )
            recommended_action = (
                "提交或 stash 主树与分支重叠的未提交改动（git add/commit 或 "
                "git stash push）后重新放行该 spec 继续 merge-back；分支与已"
                "成功实现保留"
            )
        elif cause_label.startswith("dispatch"):
            fix_hint = (
                "处置指引：等待 dispatch 锁退避（_dispatch_backoff_until）到期后"
                "自动 merge-only 重试；长时间不解除排查锁冲突根因，或人工复位 "
                "ready 重放 merge-back。"
            )
            recommended_action = (
                "等待 dispatch 锁退避到期自动重试，或排查锁冲突根因后人工复位 "
                "该 spec 继续 merge-back；分支与已成功实现保留"
            )
        else:
            fix_hint = (
                f"处置指引：提交主树 spec/changes/{spec_name}/ 目录的未提交改动"
                f"（git add/commit，含 spec 迭代修补），再把该 spec 复位 ready "
                f"重新放行 merge-back；或等待 daemon 恢复通道（recovery）下一轮再试。"
            )
            recommended_action = (
                "提交主树 spec/changes/ 目录的未提交改动"
                "（git add/commit，含 spec 迭代修补）后重新放行该 spec"
                "（ready 重派）继续 merge-back；分支与已成功实现保留"
            )
        description = (
            f"SPEC '{spec_name}' merge-back 顺延超限（{cause_label}）："
            f"自首轮顺延（{first_at}）起已连续 {retry_count} 轮仍未解除"
            f"（窗口/轮数上限已到），已停止自动重试等待人工处置。分支 "
            f"'{branch}' 保留（已成功实现、仅剩合并）。{fix_hint}"
        )
        evidence = {
            "retry_count": retry_count,
            "first_at": first_at,
            "branch": branch,
            "merge_error": str(merge_error),
            "cause": cause_label,
        }
        if selfheal_evidence:
            description = f"{description} 自愈评估：{selfheal_evidence}。"
            evidence["selfheal"] = selfheal_evidence
        self._emit_mergeback_alert(
            spec_name,
            "mergeback_spec_dir_inflight_stuck",
            {
                "error": (
                    f"mergeback spec_dir_inflight stuck after {retry_count} "
                    f"rounds since {first_at}: {str(merge_error)[:120]}"
                ),
            },
            f"mergeback spec_dir_inflight_stuck 状态上报失败 '{spec_name}'（非阻塞）",
            (
                f"'{spec_name}' merge-back 顺延超限（{cause_label}）—— 已停止自动"
                f"重试，等待人工处置后重新放行（分支与产物保留）"
            ),
            description,
            evidence,
            recommended_action,
        )

    def _report_mergeback_wip_defer_stuck(
        self, spec_name: str, retry_count: int, first_at: int,
    ) -> None:
        """WIP 等待超限降级告警（evo-add-wip-defer-merge-retry-consumer 2.1）。

        周期消费者在等待超窗口（90 分钟，对齐 code-fix defer 范式）或重试超
        轮数（6 次）时调用（``_report_mergeback_spec_dir_inflight_stuck`` 同型
        语义）：停止自动 merge-only 重试、降级为人工处置告警。现场标志
        （``_wip_gate_deferred``）保留供人工与取证——orphaned_state 探测的
        豁免随之自动失效（同一上限常量口径，admin_monitor 2.3），孤儿探测
        恢复兜底。任何异常不阻塞调用方主流程。
        """
        description = (
            f"SPEC '{spec_name}' WIP 延迟合回等待超限：自首阻（{first_at}）起已等 "
            f"{retry_count} 轮仍未解除（窗口/轮数上限已到），已停止自动 "
            f"merge-only 重试，转人工处置。分支保留（已成功实现、仅剩合并，"
            f"主树零污染）。处置指引：确认主树与分支改动路径重叠的未提交改动"
            f"归属后，提交（git add/commit）或 stash（git stash push）主树重叠"
            f"改动，再把该 spec 复位 ready 重新放行 merge-back；或人工完成合并。"
        )
        self._emit_mergeback_alert(
            spec_name,
            "mergeback_wip_defer_stuck",
            {
                "error": (
                    f"mergeback wip defer stuck after {retry_count} "
                    f"rounds since {first_at} — manual handling required"
                ),
            },
            f"mergeback wip defer stuck 状态上报失败 '{spec_name}'（非阻塞）",
            (
                f"'{spec_name}' WIP 延迟合回等待超限 —— 已停止自动重试，"
                f"等待人工处置主树重叠改动（分支与产物保留）"
            ),
            description,
            {
                "retry_count": retry_count,
                "first_blocked_at": first_at,
                "window_minutes": int(WIP_DEFER_WINDOW_MINUTES),
                "max_rounds": WIP_DEFER_MAX_ROUNDS,
            },
            (
                "人工核对主树与分支重叠的未提交改动归属后提交/stash，"
                "再把该 spec 复位 ready 重新放行 merge-back；"
                "或人工完成该分支向主树的合并"
            ),
        )