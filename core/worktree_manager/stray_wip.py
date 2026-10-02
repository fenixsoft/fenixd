"""stray_wip.py — 主树散件 WIP 周期盘点（evo-add-maintree-stray-wip-sweep）。

流水线外产生的主树 tracked 未提交改动（散件）对 merge-back 闸门不可见：
pre-dispatch/merge-back autostash 会先把主树腾空，WIP overlap 占用者识别
全程不触发；周期巡检（``reclaim_stale_autostash``）对主树脏刻意「不抢」也
不报告——散件可无限期滞留，此前只能靠 LLM 复盘车道偶然检出（滞后小时级）。

本模块补一个**旁路只读观察者**：按 daemon 主循环节拍盘点主树 tracked 未
提交改动，复用既有机械归因器（``identify_wip_occupant``）对在飞实现车道
归因；无主且宽限耗尽时经 AdminStore 发一次性 major 告警。设计决策：

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

    def _git(self, *args: str) -> "tuple[int, str] | None":
        """只读 git 子进程（超时/不可用返回 None，调用方按放弃本轮处置）。

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
        """sweep 实现体，调用方必须已持有 _main_tree_lock。"""
        wm = self.worktree_manager
        # 1) tracked-only 脏判定（口径对齐 stash_guard._list_dirty_tracked_files，
        #    复用同一实现：porcelain 脏判定 / rename 两侧计入 / untracked 不计 /
        #    路径反转义）。空集直接返回（顺手复位注册表——改动全部消失）。
        status = self._git("status", "--porcelain")
        if status is None:
            self._log(
                "warning",
                "Stray WIP sweep skipped (git status unavailable; "
                "conservative abandon, entries kept)",
            )
            return None
        files = list(wm._list_dirty_tracked_files(status_stdout=status))
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
        #    条目复位——车道终态后若仍未提交则重新起算）；零命中 → 按指纹
        #    维护 first_seen。
        identify = getattr(wm, "identify_wip_occupant", None)
        if not callable(identify):
            self._log(
                "warning",
                "Stray WIP sweep skipped (identify_wip_occupant unavailable)",
            )
            return None
        info = identify(files, list(running_run_ids or []))
        now = time.time()
        if info.holder:
            self._registry.pop(fp, None)
            self._reset_registry_absent({fp})
            return {
                "status": "holder",
                "files": files,
                "fingerprint": fp,
                "holder_run_ids": info.holder_run_ids(),
            }

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

    # ── 告警（core/code_fix._write_defer_orphan_alert 同型）─────────────

    def _write_alert(self, entry, fp, info, grace, elapsed_min) -> bool:
        """宽限耗尽升级的一次性 major 告警（经 AdminStore.append 落盘）。

        ``signal_type=maintree_stray_wip_stale``（admin_monitor 三表已登记：
        SIGNAL_SEVERITY=major / SIGNAL_RECOMMENDATION / STORED_SIGNAL_TYPES，
        漏登记则记录落 store 后无人摄取、Administrator 不唤起）。evidence 含
        文件清单/first_seen/归因证据/BLIND_SPOT_NOTE 与零触碰注记；
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
        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": SIGNAL_TYPE,
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
                    "或 stash（git stash push）主树这些改动；文件清单与滞留"
                    "起点见 evidence（worktree 分支型在飞车道之外的主树直改"
                    "形态会被按无主升级，升级仅为告警）。同指纹一次性告警，"
                    "改动消失后盘点状态自动复位"
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
