"""stray_wip.py — 主树散件 WIP 周期盘点（evo-add-maintree-stray-wip-sweep）。

流水线外产生的主树 tracked 未提交改动（散件）对 merge-back 闸门不可见：
pre-dispatch/merge-back autostash 会先把主树腾空，WIP overlap 占用者识别
全程不触发；周期巡检（``reclaim_stale_autostash``）对主树脏刻意「不抢」也
不报告——散件可无限期滞留，此前只能靠 LLM 复盘车道偶然检出（滞后小时级）。

本模块补一个**旁路只读观察者**：按 daemon 主循环节拍盘点主树 tracked 未
提交改动，复用既有机械归因器（``identify_wip_occupant``）对在飞实现车道
归因；归因到主树活交互会话的散件默认降级 info 留痕（可配置回退，见
``session_attribution_action``）；无主且宽限耗尽时经 AdminStore 发一次性
major 告警。设计决策：

- D1 计时用内容指纹，不用 mtime：改动路径排序集 + ``git diff HEAD`` 内容
  哈希（对 HEAD 求，含暂存+未暂存，与 porcelain tracked 口径一致——纯
  ``git diff`` 对纯暂存态散件为空，内容哈希会退化为空串哈希）。实证 autostash
  pop 会批量重写改动文件 mtime（纳秒级同刻），mtime 计时会被外部操作归零。
- D4 锁纪律对齐 ``stash_guard.reclaim_stale_autostash``：以非阻塞 acquire
  参与 ``_main_tree_lock`` 互斥，锁忙（merge-back 的 stash→merge→pop 临界
  区进行中）即放弃本轮——绝不与写临界区并发，也不阻塞调用方主循环。临界
  区内只调只读 git（status/diff）与不取锁的识别函数。
- D5 first_seen 注册表为 daemon 内存态，重启即重置宽限：散件仍在场会重新
  起算并最终再告警，损失仅是时效；不引入新的持久化状态文件。
- 全程零触碰：不 stash、不 checkout、不 clean、不 reset，tracked 工作区
  内容不变——盘点/告警前后 ``git status --porcelain`` 的 tracked 行逐字节
  一致（唯一落盘是 AdminStore 告警记录，属框架运行时状态目录，非主树触碰）。
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

# 告警信号类型（admin_monitor 三表登记单源，见 core/admin_monitor.py）。
SIGNAL_TYPE = "maintree_stray_wip_stale"

# untracked 散件滞留一次性告警（add-verify-evidence-placement-contract 2.1）：
# info 级「只告警不处置」。admin_monitor 仅两表登记（SIGNAL_SEVERITY /
# SIGNAL_RECOMMENDATION），**MUST NOT 收录 STORED_SIGNAL_TYPES**——摄取循环
# 对收录类型无条件唤起、无 severity 过滤，收录即把 info 留痕升级为人工唤起，
# 与降噪意图相抵（可见性由 AdminStore 留痕与 Dashboard 承载）。
UNTRACKED_SIGNAL_TYPE = "maintree_untracked_stray_stale"

# untracked 散件告警阈值缺省（entry 个数）：info 级降噪起步，低于阈值不计
# 时不告警——构建型项目散件天然多，阈值兜噪声（design 风险条目）。
DEFAULT_UNTRACKED_THRESHOLD = 5

# 宽限缺省 30 分钟（对齐 admin.mergeback_wip_orphan_grace_minutes 先例量级）。
DEFAULT_GRACE_MINUTES = 30.0

# 合理宽限上限（一天）：超限等同「无限期静默等待」，回退缺省。
_MAX_GRACE_MINUTES = 24 * 60


def grace_minutes(config) -> float:
    """散件 WIP 滞留宽限（分钟）：``admin.maintree_stray_wip_grace_minutes``。

    经 ConfigLoader 点号键读取，缺省 30（对齐 code_fix._orphan_grace_minutes
    同款守卫语义）：解析失败/负值/NaN/inf/超一天上限一律回退缺省——配置事故
    MUST NOT 放大成「无限期静默等待」极端。``0`` 是合法配置＝「耗尽即升级」
    （告警按指纹一次性去重，秒升级无刷屏风险）。
    """
    from core.config import ConfigLoader

    try:
        raw = ConfigLoader.get(
            config, "admin.maintree_stray_wip_grace_minutes",
            DEFAULT_GRACE_MINUTES,
        )
        val = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_GRACE_MINUTES
    # NaN 由 val != val 判别（NaN 使宽限比较恒假，退化为被声明禁止的极端）。
    if val != val or val < 0 or val == float("inf") or val > _MAX_GRACE_MINUTES:
        return DEFAULT_GRACE_MINUTES
    return val


def untracked_stray_threshold(config) -> int:
    """untracked 散件告警阈值（entry 个数）：``admin.maintree_untracked_stray_threshold``。

    经 ConfigLoader 点号键读取，缺省 5（info 级降噪起步）：解析失败/负值/
    NaN/inf/小于 1 一律回退缺省——阈值是降噪闸门，``0`` 会把任意 untracked
    散件都升级成告警、等同关闭降噪，按配置事故回退处理（与 grace_minutes
    允许 ``0`` 的「耗尽即升级」语义刻意不同：阈值小了只会更吵，宽限小了
    只会更早报，方向相反）。
    """
    from core.config import ConfigLoader

    try:
        raw = ConfigLoader.get(
            config, "admin.maintree_untracked_stray_threshold",
            DEFAULT_UNTRACKED_THRESHOLD,
        )
        val = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_UNTRACKED_THRESHOLD
    # NaN 由 val != val 判别；<1（含 0/负值）按配置事故回退，见 docstring。
    if val != val or val < 1 or val == float("inf"):
        return DEFAULT_UNTRACKED_THRESHOLD
    return int(val)


# 会话归因散件的盘点动作（evo-add-maintree-interactive-session-attribution 2.1）：
# ``info``＝降级 info 留痕（不派 major、不触发 admin 代查）；``keep``＝现状
# 行为（按无主走既有宽限升级）。
_SESSION_ATTRIBUTION_ACTIONS = ("info", "keep")
DEFAULT_SESSION_ATTRIBUTION_ACTION = "info"


def session_attribution_action(config) -> str:
    """会话归因散件动作：``admin.maintree_session_attribution_action``。

    ``info``（缺省）＝活会话归因散件降级 info 留痕；``keep``＝现状行为
    （视同零命中按无主走既有宽限升级）。与 ``grace_minutes`` 同型加载
    （ConfigLoader 点号键）。**非法值守卫回退 keep**（保守方向：配置事故
    MUST NOT 静默吞 major——把失效变成缺省的安全侧，对齐 grace_minutes
    守卫哲学；``info`` 只在显式合法值上生效）。code_fix defer 侧消费同一
    读取器（同键约束：keep 时 defer 侧把会话归因视同零命中走 orphan
    宽限升级流，防「盘点侧可回退、defer 侧无开关」的不对称）。
    """
    from core.config import ConfigLoader

    raw = ConfigLoader.get(
        config,
        "admin.maintree_session_attribution_action",
        DEFAULT_SESSION_ATTRIBUTION_ACTION,
    )
    val = str(raw if raw is not None else "").strip().lower()
    return val if val in _SESSION_ATTRIBUTION_ACTIONS else "keep"


class MainTreeStrayWipSweeper:
    """主树散件 WIP 周期盘点器：只读建档 + 宽限升级，零触碰。

    进程内持有 first_seen 注册表（fingerprint → 条目，D5 内存态）。由
    ``pm_engine.sweep_maintree_stray_wip`` 包装方法驱动（供在飞 run_ids 与
    WorktreeManager 句柄），无独立线程/定时器。
    """

    def __init__(self, project_root, worktree_manager, config=None, logger=None):
        self.project_root = Path(project_root)
        self.worktree_manager = worktree_manager
        self._config = config
        self._logger = logger
        # first_seen 注册表：fingerprint(hex) ->
        #   {"first_seen": epoch 秒, "first_seen_iso": str,
        #    "files": [路径...], "escalated_at": iso 或 ""}
        self._registry: dict = {}
        # untracked 散件注册表（add-verify-evidence-placement-contract 2.1）：
        # 形态同上，但指纹语义不同（两级：阈值下仅路径排序集，越过阈值后
        # 升级为追加逐文件内容 sha256 的完整指纹——untracked 不进 git diff
        # HEAD），与 tracked 注册表分账独立：
        # tracked 侧各分支按「当前 tracked 指纹集」复位，混账会被他侧清空。
        self._untracked_registry: dict = {}

    # ── 基础 ────────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str) -> None:
        if self._logger is None:
            return
        try:
            getattr(self._logger, level)("worktree_manager", msg)
        except Exception:  # noqa: BLE001 — 日志缺陷不阻断盘点
            pass

    @staticmethod
    def _iso(epoch: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))

    def _git(self, *args: str) -> "str | None":
        """只读 git 子进程：成功返回 stdout（str）；超时/不可用/非零退出码
        返回 None，调用方按放弃本轮处置。

        本方法与调用点均只发起读命令（status/diff）；任何会写工作区/索引/
        stash 栈的 git 操作都不允许出现在本模块（零触碰契约，见模块 docstring）。
        """
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root), *args],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if res.returncode != 0:
            return None
        return res.stdout

    # ── 周期入口 ────────────────────────────────────────────────────────

    def sweep(self, running_run_ids=()) -> "dict | None":
        """单轮只读盘点。返回摘要 dict；None = 本轮放弃（锁忙/git 不可用）。

        整个盘点在 worktree_manager 主树锁上非阻塞 acquire（对齐
        ``reclaim_stale_autostash`` 的锁纪律）：锁被占用即放弃本轮，条目保留
        交下轮盘点。临界区内只调只读 git 与不取锁的识别函数。
        """
        lock = getattr(self.worktree_manager, "_main_tree_lock", None)
        if lock is None:
            self._log(
                "warning",
                "Stray WIP sweep skipped (worktree_manager has no "
                "_main_tree_lock; unexpected assembly)",
            )
            return None
        if not lock.acquire(blocking=False):
            self._log(
                "info",
                "Stray WIP sweep skipped (main tree lock busy: merge-back "
                "in progress)",
            )
            return None
        try:
            return self._sweep_locked(running_run_ids)
        finally:
            lock.release()

    def _sweep_locked(self, running_run_ids=()) -> "dict | None":
        """sweep 实现体，调用方必须已持有 _main_tree_lock。

        编排两路只读口径（add-verify-evidence-placement-contract 2.1）：
        tracked 散件流（``_tracked_sweep_locked``，现行行为逐字节不变）+
        untracked 散件信号流（entry 级判定）。untracked 盘点插桩在 tracked
        空集早退**之前**——现行实现在 tracked 零改动时直接返回 clean，纯
        untracked 场景若在其后判定，信号永不触发。untracked 结果以附加键
        ``untracked``（子 dict）并入返回，既有键（status/files/fingerprint
        等）取值不变——tracked 口径零改动，消费方按增量键取用。
        """
        wm = self.worktree_manager
        # 1) tracked-only 脏判定（口径对齐 stash_guard._list_dirty_tracked_files，
        #    复用同一实现：porcelain 脏判定 / rename 两侧计入 / untracked 不计 /
        #    路径反转义）。-uall 一次取全量 stdout 供 1.5 untracked 流共用同一
        #    查询（tracked 解析跳过 ?? 行，口径不变），持锁临界区内同命令只跑
        #    一遍。空集直接返回（顺手复位注册表——改动全部消失）。
        status = self._git("status", "--porcelain", "-uall")
        if status is None:
            self._log(
                "warning",
                "Stray WIP sweep skipped (git status unavailable; "
                "conservative abandon, entries kept)",
            )
            return None
        # 1.5) untracked 散件口径（2.1）：entry 级判定（porcelain -uall 逐文件
        #      展开），豁免 .fenix/ negation 放行项与已 ignore 路径。git 查询
        #      失败按放弃本轮（保守：条目保留，与 status 不可用同款处置）。
        untracked = self._untracked_stray_entries(status_stdout=status)
        if untracked is None:
            self._log(
                "warning",
                "Stray WIP sweep skipped (untracked inventory unavailable; "
                "conservative abandon, entries kept)",
            )
            return None
        files = list(wm._list_dirty_tracked_files(status_stdout=status))
        result = self._tracked_sweep_locked(files, running_run_ids)
        if result is None:
            # tracked 侧放弃本轮（diff 失败/识别器缺失）：untracked 条目同轮
            # 保留交下轮，注册表均不复位（保守不告警）。
            return None
        if not untracked:
            self._reset_untracked_registry_absent(set())
            return result
        result["untracked"] = self._untracked_signal(untracked)
        return result

    def _tracked_sweep_locked(
        self, files: list, running_run_ids=()
    ) -> "dict | None":
        """tracked 散件流（现行行为逐字节不变）：调用方必须已持有主树锁。"""
        wm = self.worktree_manager
        if not files:
            self._reset_registry_absent(set())
            return {"status": "clean", "files": [], "fingerprint": ""}

        # 2) 内容指纹（D1）：路径排序集 + git diff HEAD 内容哈希。diff 对
        #    HEAD 求（含暂存+未暂存，与 porcelain tracked 口径一致）；diff
        #    失败按放弃本轮（保守：不建档不告警，条目保留交下轮）。
        diff = self._git("diff", "HEAD")
        if diff is None:
            self._log(
                "warning",
                "Stray WIP sweep skipped (git diff HEAD failed; "
                "conservative abandon, entries kept)",
            )
            return None
        fp = self._fingerprint(files, diff)

        # 3) 机械归因（复用 identify_wip_occupant，不重造求交逻辑）：命中
        #    在飞实现车道 → 不计时不告警（归属期间不算散件滞留，既有计时
        #    条目复位——车道终态后若仍未提交则重新起算）；命中主树活交互
        #    会话 → 默认降级 info 留痕（不派 major、不触发 admin 代查，配置
        #    keep 回退现状）；零命中 → 按指纹维护 first_seen。
        identify = getattr(wm, "identify_wip_occupant", None)
        if not callable(identify):
            self._log(
                "warning",
                "Stray WIP sweep skipped (identify_wip_occupant unavailable)",
            )
            return None
        info = identify(files, list(running_run_ids or []))
        now = time.time()
        session_attributed = info.holder and info.is_session_attribution()
        if info.holder and not session_attributed:
            self._registry.pop(fp, None)
            self._reset_registry_absent({fp})
            return {
                "status": "holder",
                "files": files,
                "fingerprint": fp,
                "holder_run_ids": info.holder_run_ids(),
            }
        if session_attributed and session_attribution_action(self._config) != "keep":
            # 会话归因散件降级 info 留痕（2.1）：计时/复位与在飞车道命中
            # 分支同型（pop 计时条目、指纹消失即复位）。留痕走盘点结构化
            # 返回值与既有日志通道，MUST NOT 新增 AdminStore signal_type
            # （免 admin_monitor 三表登记缺口——漏登记则落 store 后无人摄取）。
            self._registry.pop(fp, None)
            self._reset_registry_absent({fp})
            session = next(iter(info.holders), {}).get("session") or {}
            self._log(
                "info",
                f"主树散件 WIP 归因到主树活交互会话，降级 info 留痕（不派"
                f" major 不触发 admin 代查）: {', '.join(files)}; "
                f"{info.describe()}",
            )
            return {
                "status": "session-attributed",
                "files": files,
                "fingerprint": fp,
                "session_signals": list(session.get("signals") or []),
            }
        # 落入无主流形的两种情况共用既有宽限升级流：真零命中，或会话归因被
        # 配置 keep 回退（视同零命中走现状行为——配置事故/人工回退保守方向）。
        if session_attributed:
            self._log(
                "info",
                "会话归因散件按 admin.maintree_session_attribution_action=keep "
                "回退现状行为（视同零命中走无主宽限升级）",
            )

        entry = self._registry.get(fp)
        if entry is None:
            entry = {
                "first_seen": now,
                "first_seen_iso": self._iso(now),
                "files": files,
                "escalated_at": "",
            }
            self._registry[fp] = entry
        else:
            # 指纹不变沿用原 first_seen（D1：mtime 不可信，绝不归零重计）；
            # 仅刷新文件快照供告警 evidence 取最新清单。
            entry["files"] = files

        # 4) 宽限耗尽 → 一次性 major 告警（同指纹先查后记去重）。
        grace = grace_minutes(self._config)
        elapsed_min = (now - entry["first_seen"]) / 60.0
        alerted = False
        if elapsed_min >= grace and not entry.get("escalated_at"):
            if self._write_alert(entry, fp, info, grace, elapsed_min):
                entry["escalated_at"] = self._iso(now)
                alerted = True

        # 5) 状态复位：指纹不再出现的条目清除（不告警不残留）。
        self._reset_registry_absent({fp})
        return {
            "status": "alerted" if alerted else "orphan-timed",
            "files": files,
            "fingerprint": fp,
            "first_seen_iso": entry["first_seen_iso"],
            "grace_minutes": grace,
            "elapsed_minutes": round(elapsed_min, 3),
        }

    # ── 指纹 / 注册表 ───────────────────────────────────────────────────

    @staticmethod
    def _fingerprint(files: list, diff_head: str) -> str:
        """改动集指纹（D1）：路径排序集 + ``git diff HEAD`` 内容哈希。

        ``git diff HEAD`` 对 HEAD 求，含暂存+未暂存——纯 ``git diff`` 对纯
        暂存态散件为空、哈希会退化为空串哈希，故不用。路径集与内容哈希用
        NUL 分隔，防「文件列表拼接歧义」撞指纹。
        """
        h = hashlib.sha256()
        h.update("\x00".join(sorted(str(p) for p in files)).encode("utf-8"))
        h.update(b"\x00\x00")
        h.update(diff_head.encode("utf-8"))
        return h.hexdigest()

    def _reset_registry_absent(self, current_fingerprints: set) -> None:
        """清除指纹不再出现的注册表条目（1.5 状态复位：不告警不残留）。"""
        for fp in [k for k in self._registry if k not in current_fingerprints]:
            del self._registry[fp]

    # ── untracked 散件口径（add-verify-evidence-placement-contract 2.1）──

    def _untracked_stray_entries(
        self, status_stdout: "str | None" = None
    ) -> "list[str] | None":
        """untracked 散件清单（entry 级，已豁免放行项与 ignore 路径）。

        - ``git status --porcelain -uall``：untracked 逐文件展开（目录不折叠
          成 ``dir/``），entry 级判定由此保证——混合目录里已 tracked 条目不
          出现在 untracked 清单（verify-evidence/ 内已 tracked 条目不误报）；
        - 豁免①：``.fenix/`` negation 放行项——``git check-ignore -v -n
          --non-matching`` 对被 ``!`` 否定规则显式放行的路径输出以 ``!`` 开头
          的规则行（如 ``!.fenix/verify.yaml``，实测样本：.fenix/ 为混合目录
          时放行项恰恰以 ``??`` 形态出现在 porcelain 里），这是「框架有意
          放行的运行时状态文件」的机械判据，零 .gitignore 自解析；
        - 豁免②：已 ignore 路径——porcelain 缺省不列 ignored，check-ignore
          复核兜底（非 ``!`` 规则命中的同样不计）；
        - 无任何忽略规则的 ``.fenix/`` 证据散件**不豁免**（design 风险条目：
          契约不依赖消费项目忽略规则成立，此类散件由本信号兜底可见性）。

        Args:
            status_stdout: 已取回的 ``git status --porcelain -uall`` stdout，
                传入时跳过子进程直接解析——``_sweep_locked`` 持锁临界区内
                tracked 流与 untracked 流共用同一次查询、同命令只跑一遍
                （与 ``_list_dirty_tracked_files(status_stdout=...)`` 同款手法）。

        git 查询失败返回 None（调用方按放弃本轮处置，条目保留）。check-ignore
        以 --stdin 批量一次调用（散件多时避免逐路径子进程）；``-n
        --non-matching`` 保证每个输入路径都有输出行（未匹配输出 ``::\t路径``），
        按输出末列回映射、不依赖行序。
        """
        if status_stdout is None:
            status_stdout = self._git("status", "--porcelain", "-uall")
            if status_stdout is None:
                return None
        out = status_stdout
        from core.worktree_manager.mergeback import _unquote_git_path

        paths: list = []
        for line in out.splitlines():
            if not line.startswith("?? "):
                continue
            raw = line[3:].strip()
            if raw:
                paths.append(_unquote_git_path(raw))
        if not paths:
            return []
        detail = self._git_check_ignore_detail(paths)
        if detail is None:
            return None
        entries = []
        for p in paths:
            pattern = detail.get(p)
            if pattern is None:
                # check-ignore 未回该路径（异常形态）→ 保守不计入（宁漏勿误报）
                continue
            if not pattern:
                entries.append(p)  # 无规则命中＝真散件
            # 非 ``!`` 规则命中＝已 ignore（豁免②）；``!`` 开头＝negation
            # 放行项（豁免①）——两者都不计入。
        return sorted(entries)

    def _git_check_ignore_detail(self, paths: list) -> "dict[str, str] | None":
        """批量 ``git check-ignore -v -n --non-matching --stdin``。

        返回 路径 → 匹配规则（未匹配 ``::`` 行归一为空串）；check-ignore 退出
        码语义特殊（0=存在 ignored，1=全部未 ignored），1 是合法终态——与
        ``_git`` 的「非零即失败」不同，此处只把超时/不可用/128 视为失败返回
        None。规则行左段形如 ``<source>:<linenum>:<pattern>``，按前两个冒号切
        分取 pattern（源文件路径含冒号的罕见形态由末列路径回映射兜住正确性）。
        """
        try:
            res = subprocess.run(
                [
                    "git", "-C", str(self.project_root),
                    "check-ignore", "-v", "-n", "--non-matching", "--stdin",
                ],
                input="\n".join(paths) + "\n",
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if res.returncode not in (0, 1):
            return None
        detail: dict = {}
        for line in res.stdout.splitlines():
            if "\t" not in line:
                continue
            left, echoed = line.split("\t", 1)
            # [fenix-ignore:6db071347e0f] source 含冒号致 pattern 段错位不改变结果：唯一消费方 _untracked_stray_entries 对「! 放行」与「非 ! 命中」均不计入散件（豁免①②同效），非空 pattern 恒走豁免，散件清单与告警可见性不受影响（实测错位/正确两种解析 entries 全等）。
            parts = left.split(":", 2)
            detail[echoed] = parts[2] if len(parts) == 3 else ""
        return detail

    def _untracked_signal(self, entries: list) -> dict:
        """untracked 散件滞留信号流（2.1）：阈值闸门 + 宽限计时 + 一次性告警。

        记账/复位复用 tracked 形态（first_seen 注册表、同指纹一次性、指纹
        消失自动复位），注册表独立（``_untracked_registry``）。阈值
        （``admin.maintree_untracked_stray_threshold``，缺省 5）之下不告警
        但照常建档计时（两级指纹的路径级，零文件读盘）；越过阈值升级为
        内容级完整指纹，升级当刻 fp 变化、计时自然重起，此后稳定期内沿用
        原 first_seen 不重计。宽限复用
        ``admin.maintree_stray_wip_grace_minutes``
        （同族同语义，不膨胀配置面）。只告警不处置：info 级 AdminStore 留痕，
        不派 major、不唤起人工。

        Returns: 子 dict（并入 sweep 返回的 ``untracked`` 键）：status 取
        ``below-threshold`` / ``timed`` / ``alerted``。
        """
        threshold = untracked_stray_threshold(self._config)
        count = len(entries)
        below_threshold = count < threshold
        # 两级指纹（常态开销收敛）：低于阈值仅按路径排序集建档计时（零文件
        # 读盘，IO 与散件内容规模解耦）；越过阈值升级为含内容 sha256 的完整
        # 指纹。级别切换改变 fp → 升级当刻计时自然重起（语义损失可控），
        # 同级别稳定期内沿用原 first_seen 不重计（与 tracked 流 D1 同款）。
        fp = self._untracked_fingerprint(
            entries, include_content=not below_threshold
        )
        now = time.time()
        entry = self._untracked_registry.get(fp)
        if entry is None:
            entry = {
                "first_seen": now,
                "first_seen_iso": self._iso(now),
                "files": list(entries),
                "escalated_at": "",
            }
            self._untracked_registry[fp] = entry
        else:
            # 指纹不变沿用原 first_seen（与 tracked 流 D1 同款：不归零重计）；
            # 仅刷新文件快照供告警 evidence 取最新清单。
            entry["files"] = list(entries)
        self._reset_untracked_registry_absent({fp})

        if below_threshold:
            return {
                "status": "below-threshold",
                "files": list(entries),
                "count": count,
                "threshold": threshold,
                "fingerprint": fp,
            }
        grace = grace_minutes(self._config)
        elapsed_min = (now - entry["first_seen"]) / 60.0
        alerted = False
        if elapsed_min >= grace and not entry.get("escalated_at"):
            if self._write_untracked_alert(entry, fp, threshold, grace, elapsed_min):
                entry["escalated_at"] = self._iso(now)
                alerted = True
        return {
            "status": "alerted" if alerted else "timed",
            "files": list(entries),
            "count": count,
            "threshold": threshold,
            "fingerprint": fp,
            "first_seen_iso": entry["first_seen_iso"],
            "grace_minutes": grace,
            "elapsed_minutes": round(elapsed_min, 3),
        }

    def _untracked_fingerprint(self, entries: list, include_content: bool = True) -> str:
        """untracked 散件指纹（2.1）：路径排序集（+ 可选逐文件内容 sha256）。

        不可复用 tracked 形态（``git diff HEAD`` 哈希）：untracked 条目不进
        diff，复用会退化为纯路径集哈希——日志追加/转储重写等内容演化不再被
        计入，「同内容滞留」与「持续演化」两种形态不可分。路径与内容哈希用
        NUL 分隔，防「文件列表拼接歧义」撞指纹（与 ``_fingerprint`` 同款）。
        盘点与哈希之间文件被删改的竞态（OSError）按占位标记参与哈希：该
        entry 下轮指纹自然变化、计时重起，不虚构内容哈希。

        两级形态（常态开销收敛）：``include_content=False`` 只哈希路径排序
        集、零文件读盘——低于降噪阈值的常态轮次用此级建档计时，IO 与散件
        内容规模解耦；``include_content=True`` 追加逐文件 sha256（越过阈值
        后的告警判定级）。级别切换改变 fp 值，计时在升级当刻自然重起。
        """
        h = hashlib.sha256()
        rels = sorted(str(p) for p in entries)
        h.update("\x00".join(rels).encode("utf-8"))
        h.update(b"\x00\x00")
        if not include_content:
            return h.hexdigest()
        for rel in rels:
            digest = hashlib.sha256()
            try:
                with open(self.project_root / rel, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        digest.update(chunk)
                content_fp = digest.hexdigest()
            except OSError:
                content_fp = "unreadable"
            h.update(rel.encode("utf-8"))
            h.update(b"\x00")
            h.update(content_fp.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    def _reset_untracked_registry_absent(self, current_fingerprints: set) -> None:
        """清除指纹不再出现的 untracked 注册表条目（指纹消失自动复位）。"""
        for fp in [
            k for k in self._untracked_registry if k not in current_fingerprints
        ]:
            del self._untracked_registry[fp]

    def _write_untracked_alert(self, entry, fp, threshold, grace, elapsed_min) -> bool:
        """untracked 散件滞留一次性 info 告警（经 AdminStore.append 落盘）。

        ``signal_type=maintree_untracked_stray_stale``：admin_monitor 仅两表
        登记（SIGNAL_SEVERITY=info / SIGNAL_RECOMMENDATION「只告警不处置」
        模板），**MUST NOT 收录 STORED_SIGNAL_TYPES**——摄取循环对收录类型
        无条件唤起、无 severity 过滤，收录即把 info 留痕升级为人工唤起。
        可见性由 AdminStore 留痕与 Dashboard 承载。AdminStore 拒写时返回
        False（escalated_at 不落、下轮重试），不让告警静默蒸发。
        """
        from core.admin_store import AdminStore, SIGNAL

        files = list(entry.get("files") or [])
        evidence = (
            f"项目名={self.project_root.name}; "
            f"first_seen={entry.get('first_seen_iso') or '?'}; "
            f"滞留={round(elapsed_min, 1)}分钟; 宽限={grace:g}分钟; "
            f"阈值={threshold}个entry; 指纹={fp[:16]}; "
            f"文件清单({len(files)}): {', '.join(files) or '无'}; "
            f"计时口径: 内容指纹（untracked 路径排序集 + 逐文件内容 sha256"
            f"——untracked 不进 git diff HEAD，不可复用 tracked 指纹形态）; "
            f"豁免注记: .fenix/ negation 放行项与已 ignore 路径不计入; "
            f"零触碰注记: 本盘点只读（未执行 stash/checkout/clean/reset），"
            f"告警发出前后主树工作区状态未变"
        )
        store = AdminStore(self.project_root, logger=None)
        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": UNTRACKED_SIGNAL_TYPE,
                "spec": None,
                "severity": "info",
                "description": (
                    "主树 untracked 散件超阈值滞留（周期盘点，info 级只告警"
                    f"不处置）：{len(files)} 个 untracked entry 自 first_seen "
                    f"起超过宽限 {grace:g} 分钟。本告警不派生任何自动处置、"
                    "不唤起人工，仅留痕供 Dashboard 呈现与人工核查"
                ),
                "evidence": evidence,
                "source": "maintree-stray-wip-sweep",
                "recommended_action": (
                    "只告警不处置（info 级）：人工按需核对主树这些 untracked "
                    "文件归属，挪入证据落位目录 .fenix/verify-evidence/<spec>/、"
                    "补 ignore 规则或删除；文件清单与滞留起点见 evidence。"
                    "同指纹一次性告警，指纹消失后盘点状态自动复位"
                ),
            }
        )
        if rec is None:
            self._log(
                "warning",
                f"{UNTRACKED_SIGNAL_TYPE}: 告警写入被拒（AdminStore 拒写），"
                f"未落盘——本轮不计升级标记，下轮盘点重试",
            )
            return False
        self._log(
            "info",
            f"{UNTRACKED_SIGNAL_TYPE}: 主树 untracked 散件超阈值滞留"
            f"（{len(files)} entry，first_seen={entry.get('first_seen_iso')}）"
            f"已发一次性 info 告警: {', '.join(files)}",
        )
        return True

    # ── 告警（core/code_fix._write_defer_orphan_alert 同型）─────────────

    def _write_alert(self, entry, fp, info, grace, elapsed_min) -> bool:
        """宽限耗尽升级的一次性 major 告警（经 AdminStore.append 落盘）。

        ``signal_type=maintree_stray_wip_stale``（admin_monitor 三表已登记：
        SIGNAL_SEVERITY=major / SIGNAL_RECOMMENDATION / STORED_SIGNAL_TYPES，
        漏登记则记录落 store 后无人摄取、Administrator 不唤起）。evidence 含
        文件清单/first_seen/归因证据/BLIND_SPOT_NOTE 与零触碰注记；记录附
        choices 快照（evo-add-commit-stray-wip-choice 2.2，commit_stray_wip），
        recommended_action 指向人工提交或 stash（无 spec 可重派，姊妹信号
        ``mergeback_wip_orphan_stuck`` 同款批语义适配）。AdminStore 拒写时
        返回 False（escalated_at 不落、下轮重试），不让告警静默蒸发。
        """
        from core.admin_store import AdminStore, SIGNAL
        from core.worktree_manager.types import WipOccupantInfo

        files = list(entry.get("files") or [])
        evidence = (
            f"项目名={self.project_root.name}; "
            f"first_seen={entry.get('first_seen_iso') or '?'}; "
            f"滞留={round(elapsed_min, 1)}分钟; 宽限={grace:g}分钟; "
            f"指纹={fp[:16]}; "
            f"文件清单({len(files)}): {', '.join(files) or '无'}; "
            f"归因证据: {info.describe()}; "
            f"计时口径: 内容指纹（改动路径集 + git diff HEAD 哈希），不依赖 "
            f"mtime——autostash pop 会批量重写改动文件 mtime; "
            f"零触碰注记: 本盘点只读（未执行 stash/checkout/clean/reset），"
            f"告警发出前后主树工作区状态未变"
        )
        store = AdminStore(self.project_root, logger=None)
        # evo-add-commit-stray-wip-choice 2.2：发射点快照 choices（照
        # mergeback.py 先例）。注册表为单源（缺键回退），告警是历史事实，
        # 注册表演进不回写历史告警的选项集。局部导入避免模块级环依赖。
        from core.dashboard.data.adjudication_choices import choices_for

        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": SIGNAL_TYPE,
                "choices": list(choices_for(SIGNAL_TYPE)),
                "spec": None,
                "severity": "major",
                "description": (
                    "主树 tracked 未提交改动（散件 WIP）经周期盘点确认为无主"
                    f"滞留：{len(files)} 个文件自 first_seen 起超过宽限 "
                    f"{grace:g} 分钟无人认领（在飞实现车道分支改动集零命中）。"
                    "盘点只读零触碰，等待人工提交或 stash 处置"
                ),
                "evidence": evidence,
                "source": "maintree-stray-wip-sweep",
                "recommended_action": (
                    "人工核对主树这些未提交改动的归属后，提交（git add/commit）"
                    "或 stash（git stash push）主树这些改动；或执行裁决选项 "
                    "commit_stray_wip 一键提交信号清单内文件（与 stash 类动作"
                    "互斥，处置记录附提交 hash）。文件清单与滞留起点见 "
                    "evidence（worktree 分支型在飞车道之外的主树直改形态会被"
                    "按无主升级，升级仅为告警）。同指纹一次性告警，改动消失后"
                    "盘点状态自动复位"
                ),
            }
        )
        if rec is None:
            self._log(
                "warning",
                f"{SIGNAL_TYPE}: 告警写入被拒（AdminStore 拒写），未落盘——"
                f"本轮不计升级标记，下轮盘点重试",
            )
            return False
        self._log(
            "warning",
            f"{SIGNAL_TYPE}: 主树散件 WIP 滞留宽限耗尽（{len(files)} 文件，"
            f"first_seen={entry.get('first_seen_iso')}）已发一次性 major 告警"
            f": {', '.join(files)}",
        )
        return True
