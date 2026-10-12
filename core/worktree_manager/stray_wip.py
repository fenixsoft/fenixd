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
- D5 first_seen 注册表原为 daemon 内存态，重启即重置宽限：散件仍在场会重新
  起算并最终再告警，损失仅是时效；不引入新的持久化状态文件。**该决策自
  evo-persist-stray-escalation-clock 起对 untracked 注册表被显式取代**：
  实证 daemon 重启间隔（最长约 11 小时）远短于 24 小时滞留升级阈值，
  重启重置使升级永不触发、同指纹一次性告警被击穿成重复多条——untracked
  注册表现落盘 ``.fenix/`` 运行时状态区（``_untracked_registry_path``），
  重启后恢复 first_seen 与双档升级标记，跨重启连续计时/去重；tracked 流
  维持内存态（决策原文对 tracked 流继续有效，重启重置宽限的损失仅时效）。
- 全程零触碰：不 stash、不 checkout、不 clean、不 reset，tracked 工作区
  内容不变——盘点/告警前后 ``git status --porcelain`` 的 tracked 行逐字节
  一致（落盘仅两处，均属框架运行时状态目录、非主树触碰：AdminStore 告警
  记录，与 untracked 注册表持久化文件——后者在 ``.fenix/`` 忽略区内，
  不入库、也不计入 untracked 散件盘点）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

# 告警信号类型（admin_monitor 三表登记单源，见 core/admin_monitor.py）。
SIGNAL_TYPE = "maintree_stray_wip_stale"

# untracked 散件滞留一次性告警（add-verify-evidence-placement-contract 2.1）：
# info 级「只告警不处置」。admin_monitor 仅两表登记（SIGNAL_SEVERITY /
# SIGNAL_RECOMMENDATION），**MUST NOT 收录 STORED_SIGNAL_TYPES**——摄取循环
# 对收录类型无条件唤起、无 severity 过滤，收录即把 info 留痕升级为人工唤起，
# 与降噪意图相抵（可见性由 AdminStore 留痕与 Dashboard 承载）。
# evo-stray-untracked-escalation 显式修订上述裁定的适用边界：**info 信号本身
# 维持不收录，第二档升级信号（下常量）除外**——滞留时长或体积触顶时以
# major 升级并接入自动唤起，本信号的一次性 info 留痕语义不变。
UNTRACKED_SIGNAL_TYPE = "maintree_untracked_stray_stale"

# untracked 散件第二档升级信号（evo-stray-untracked-escalation 1.2）：severity
# major、经 admin_monitor 三表登记接入自动唤起（SIGNAL_SEVERITY /
# SIGNAL_RECOMMENDATION / STORED_SIGNAL_TYPES + 摄取项目名解析清单）。
UNTRACKED_ESCALATED_SIGNAL_TYPE = "maintree_untracked_stray_escalated"

# 目录型产物集合首现提示（evo-stray-first-sight-prevention 1.1）：info 级
# 「只提示不处置」，admin_monitor 仅两表登记（SIGNAL_SEVERITY /
# SIGNAL_RECOMMENDATION，info 先例 maintree_untracked_stray_stale），
# **MUST NOT 收录 STORED_SIGNAL_TYPES**——不自动唤起 admin run，否则提示
# 本身就变成新的浪费形态（proposal 风险条目）；也不启动升级时钟（24h 滞留
# /体积阈值的既有起点不变）。消费面为告警面板展示与后续评审/处置的背景
# 信息；建议面语义：提示只携带预防性 .gitignore 草案，ignore 动作仍走既有
# 裁决执行器或人工（盘点零写副作用）。
UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE = "maintree_untracked_stray_first_sight"

# 白名单脱落信号（evo-whitelist-tracked-patrol 1.1）：被 .gitignore `!`
# 放行规则显式放行（＝声明了入库意图）却不在 git 索引中的路径——白名单
# 约定「状态文件随仓库入库」的机械反差，几乎必然是脱落事故（实证：c91213f
# 误删 .fenix/verify.yaml 后盘上 untracked 副本掩盖问题 6 天——negation
# 豁免让散件流正确地不计入它，豁免之后零机制反向核查 tracked 状态）。
# severity major、admin_monitor 三表登记接入自动唤起（对齐
# maintree_untracked_stray_escalated 先例）；即时发射无阈值无宽限（脱落
# 无「滞留容忍」语义）；不自动执行 git add 类修复动作，信号只唤起人工/裁决
# 处置（处置二选一：git add 恢复入库，或删除放行规则承认其为运行时文件）。
WHITELIST_UNTRACKED_SIGNAL_TYPE = "whitelist_untracked"

# 第二档升级滞留时长阈值（分钟）：24 小时（proposal 验收口径）。
UNTRACKED_ESCALATION_STALE_MINUTES = 24 * 60.0

# 第二档升级体积阈值缺省（字节）：500MB，可配（见
# untracked_stray_size_threshold_bytes）。
DEFAULT_UNTRACKED_ESCALATION_BYTES = 524288000

# untracked 散件告警阈值缺省（entry 个数）：info 级降噪起步，低于阈值不计
# 时不告警——构建型项目散件天然多，阈值兜噪声（design 风险条目）。
DEFAULT_UNTRACKED_THRESHOLD = 5

# 宽限缺省 30 分钟（对齐 admin.mergeback_wip_orphan_grace_minutes 先例量级）。
DEFAULT_GRACE_MINUTES = 30.0

# 合理宽限上限（一天）：超限等同「无限期静默等待」，回退缺省。
_MAX_GRACE_MINUTES = 24 * 60

# untracked 注册表持久化文件（相对 project_root，evo-persist-stray-escalation
# 1.1）：.fenix/ 运行时状态区（与 restart_history.jsonl 同区）。消费仓库
# .gitignore 均有 ``.fenix/*``（或 ``.fenix/``）规则——文件不入库、也不被
# untracked 盘点计入散件（已 ignore 路径豁免，``_untracked_stray_entries``
# 豁免②）。文件缺失/损坏回退空表重新宽限（fail-open，不阻断主盘点）。
UNTRACKED_REGISTRY_RELPATH = ".fenix/stray_untracked_registry.json"

# 持久化条目字段白名单：与现行内存条目同构（first_seen/first_seen_iso/
# files/escalated_at/escalated_signal_at）。``sizes_bytes``/``total_bytes``
# 是每轮盘点的现采值，不持久化（design 1：落盘只承载时钟与标记，体积
# 升级判定用当轮现采数据）。双档标记 MUST 随注册表持久化：升级标记若丢
# 失，恢复的 first_seen（往往已 ≥24h）会在重启后首轮盘点重复发出升级信号，
# 违背「同一集合只升级一次」语义。
_UNTRACKED_PERSISTED_FIELDS = (
    "first_seen",
    "first_seen_iso",
    "files",
    "escalated_at",
    "escalated_signal_at",
)

# 持久化文件分区键（evo-stray-first-sight-prevention 1.2）：首现登记以独立
# 目录键结构与 untracked 指纹注册表同居一个持久化文件
# （``UNTRACKED_REGISTRY_RELPATH``），顶层两分区各司其键空间——目录路径
# 与 sha256 指纹不共享命名空间，混排会被既有 absent 复位（按「当轮指纹集」
# 清除）逐轮误清。载入对旧版扁平形态（顶层即指纹→条目，首现登记尚未存在）
# 做 legacy 适配：整体归入 untracked 分区、首现登记空表起步。
_UNTRACKED_SECTION_KEY = "untracked"
_FIRST_SIGHT_SECTION_KEY = "first_sight_dirs"

# 首现登记条目持久化字段白名单（同 ``_UNTRACKED_PERSISTED_FIELDS`` 投影
# 机制）：登记只承载「目录已见过」这一去重事实与证据快照，无升级时钟、
# 无双档标记语义。
_FIRST_SIGHT_PERSISTED_FIELDS = ("first_seen", "first_seen_iso", "files")


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


def untracked_stray_size_threshold_bytes(config) -> int:
    """untracked 散件第二档升级体积阈值（字节）：
    ``admin.maintree_untracked_stray_size_threshold_bytes``。

    经 ConfigLoader 点号键读取，缺省 524288000（500MB，proposal 验收口径，
    仿 ``untracked_stray_threshold`` 的可配范式）：解析失败/负值/NaN/inf/
    小于 1 一律回退缺省——阈值是升级降噪闸门，``0`` 会把任意体积的滞留
    集合都升级成 major 唤起、等同关闭降噪，按配置事故回退处理（与
    untracked_stray_threshold 同款守卫哲学）。
    """
    from core.config import ConfigLoader

    try:
        raw = ConfigLoader.get(
            config, "admin.maintree_untracked_stray_size_threshold_bytes",
            DEFAULT_UNTRACKED_ESCALATION_BYTES,
        )
        val = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_UNTRACKED_ESCALATION_BYTES
    # NaN 由 val != val 判别；<1（含 0/负值）按配置事故回退，见 docstring。
    if val != val or val < 1 or val == float("inf"):
        return DEFAULT_UNTRACKED_ESCALATION_BYTES
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


def _porcelain_untracked_paths(status_stdout: str) -> list:
    """``git status --porcelain -uall`` 的 untracked 逐文件路径清单。

    untracked 散件流与白名单脱落流的共同候选源（两流共用同一份 porcelain
    解析，``-uall`` 保证目录不折叠成 ``dir/``、entry 级判定成立）。``?? ``
    行按「反转义后末列」取路径（quoted-form 还原，与 mergeback 同款）。
    """
    from core.worktree_manager.mergeback import _unquote_git_path

    paths: list = []
    for line in status_stdout.splitlines():
        if not line.startswith("?? "):
            continue
        raw = line[3:].strip()
        if raw:
            paths.append(_unquote_git_path(raw))
    return paths


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
        # 双档 escalated 标记（evo-stray-untracked-escalation 1.2）：
        # ``escalated_at``＝info 一次性告警标记；``escalated_signal_at``＝
        # 第二档升级信号标记——同一集合只升级一次。体积采集随注册表输出
        # （``sizes_bytes`` 逐条目字节 / ``total_bytes`` 集合合计）。
        # 本注册表随 evo-persist-stray-escalation 落盘持久化（D5 取代注记）：
        # ``_untracked_registry_loaded`` 守卫每进程只载入一次（盘点开始时），
        # 内存态此后为单源；``_untracked_persisted_payload`` 缓存上次落盘
        # 序列化结果，盘点收尾无变更不重写。
        self._untracked_registry: dict = {}
        self._untracked_registry_loaded = False
        self._untracked_persisted_payload: "str | None" = None
        # 首现登记表（evo-stray-first-sight-prevention 1.2）：规范化根目录
        # （str）-> {"first_seen": epoch 秒, "first_seen_iso": str,
        # "files": [该目录下散件条目快照...]}。去重键为目录路径，MUST NOT
        # 复用条目集指纹——双层指纹随集合增删/跨阈值档切换漂移
        # （stray_wip.py::_untracked_signal），按指纹去重会在散件增长时重复
        # 提示；且 ``_reset_untracked_registry_absent`` 只保留当轮指纹，目录
        # 级条目混入同表会被每轮清除（独立分账）。随持久化文件分区落盘
        # （``_FIRST_SIGHT_SECTION_KEY``），跨重启不重复提示。
        self._first_sight_dirs: dict = {}
        # 白名单脱落注册表（evo-whitelist-tracked-patrol 1.1）：形态同上，
        # 指纹语义＝放行-未跟踪路径排序集 + 逐文件内容 sha256（复用
        # ``_untracked_fingerprint``，untracked 不可复用 tracked 指纹形态的
        # 同款论证适用）。与 tracked/untracked 注册表分账独立：各流按「当前
        # 指纹集」复位，混账会被他侧清空。``rules`` 键随条目留存 check-ignore
        # 放行规则快照，供告警 evidence 取证。
        self._whitelist_registry: dict = {}
        # 会话归因留痕去重状态（evo-maintree-stray-attribution-log-dedup 1.1）：
        # 进程内内存态，不落 AdminStore（模块注释明令不新增 signal_type）。
        # ``_last_session_attr``＝上次留痕键 (路径排序文件集, 占用者会话
        # identity)：路径排序对齐 ``_fingerprint``「路径排序集」惯例，防调用方
        # 文件顺序抖动击穿去重；会话标识取 info.holders 首项 session 字典的
        # identity 字段（mergeback 会话 clue 构造同名、types.describe 渲染
        # 「会话=」同源），取不到用空串占位。``_attr_suppress_count``＝自上次
        # 留痕起被抑制的轮数；``_attr_last_log_ts``＝上次留痕时间戳
        # （time.time() 单调比较）。不做跨重启持久化：重启丢状态仅损失重启后
        # 首轮一条重复留痕，与 tracked 流 first_seen 内存态同一取舍（上方 D5）。
        self._last_session_attr: "tuple | None" = None
        self._attr_suppress_count = 0
        self._attr_last_log_ts = 0.0
        # keep 回退注记去重状态（两流各一槽，防互相抑制）：回退注记为静态
        # 文案（无文件身份），键去重不适用、按 60 分钟窗聚合即可；独立于
        # 上方三态留痕状态——那套被 ``_release_session_attr_if_gone`` 复位且
        # 与 R3 闭环绑定，混入回退态会在归因消失轮误触「解除」行。
        self._keep_fallback_tracked_ts = 0.0
        self._keep_fallback_untracked_ts = 0.0

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
                encoding="utf-8",
                errors="replace",
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
            # 持久化时钟（evo-persist-stray-escalation 1.1/1.2）：盘点开始时
            # 载入（每进程一次，重启恢复 first_seen 与双档升级标记）；收尾
            # （含本轮放弃路径）惰性清理失效路径后按变更原子落盘。载入失败
            # fail-open（回退空表告警），落盘失败仅告警——持久化缺陷 MUST
            # NOT 放大成本轮盘点失败。内层 finally 先于锁释放执行（落盘在
            # 持锁临界区内完成，写的是 .fenix/ 忽略区运行时文件，零触碰）。
            self._load_untracked_registry()
            try:
                return self._sweep_locked(running_run_ids)
            finally:
                self._prune_untracked_registry_stale_paths()
                self._persist_untracked_registry()
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
        #      check-ignore 批量通道一次取回、untracked 流与白名单脱落流
        #      （evo-whitelist-tracked-patrol 1.1）共用同一次查询——持锁临界
        #      区内同命令只跑一遍（与 status 共用同款纪律），两流各取各的
        #      判定（放行项此处豁免不计散件、彼处恰是检测目标），互不污染。
        stray_paths = _porcelain_untracked_paths(status)
        check_detail = (
            self._git_check_ignore_detail(stray_paths) if stray_paths else {}
        )
        if stray_paths and check_detail is None:
            self._log(
                "warning",
                "Stray WIP sweep skipped (check-ignore inventory unavailable; "
                "conservative abandon, entries kept)",
            )
            return None
        untracked = self._untracked_stray_entries(
            status_stdout=status, detail=check_detail
        )
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
        # 1.6) 白名单脱落口径（evo-whitelist-tracked-patrol 1.1）：`!` 放行 +
        #      不在索引＝白名单脱落。插桩在 untracked 空集早退**之前**（与
        #      untracked 流插桩理由同款：早退不得吞掉本流判定），结果以附加键
        #      ``whitelist_untracked`` 并入返回。
        result["whitelist_untracked"] = self._whitelist_signal(
            stray_paths, check_detail
        )
        if not untracked:
            self._reset_untracked_registry_absent(set())
            # 首现登记同款 absent 复位（evo-stray-first-sight-prevention 1.2）：
            # 零散件轮＝所有目录都不再贡献条目，整表复位——复位后再现视为
            # 新首现（proposal：目录消失走既有复位逻辑）。
            self._reset_first_sight_registry_absent(set())
            return result
        result["untracked"] = self._untracked_signal(untracked, running_run_ids)
        return result

    def _tracked_sweep_locked(
        self, files: list, running_run_ids=()
    ) -> "dict | None":
        """tracked 散件流（现行行为逐字节不变）：调用方必须已持有主树锁。"""
        wm = self.worktree_manager
        if not files:
            # 归因解除判定先行（文件消失迁移）：clean 早退到不了归因分支，
            # 见 _release_session_attr_if_gone（1.3 单点判定的消失分支调用）。
            self._release_session_attr_if_gone(False, files)
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
        # 归因解除单点判定（1.3）：挂在归因分支之前，MUST NOT 依赖归因分支
        # 被执行——占用者整体清空时 info.holder 为假（session_attributed=
        # False）、归因迁至在飞车道时 is_session_attribution() 为假，两种
        # 迁移归因分支都不进入、键比较不发生；宽限升级处置接管前必经「归因
        # 消失轮」（会话归因散件每轮被 pop/复位、不入 first_seen 注册表，
        # 自身永不升级），由本判定覆盖。
        self._release_session_attr_if_gone(bool(session_attributed), files)
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
            # 留痕三态（1.2，evo-maintree-stray-attribution-log-dedup）：键＝
            # (路径排序文件集, 占用者会话 identity)。键变化（首次/文件集变化/
            # 占用者变化）落全量行（沿用现文案）；键稳定且距上次留痕满 60
            # 分钟落 1 条聚合行（含重复计数）；其余轮次静默计数——归因结论
            # 稳定时不再逐轮重写同一行（5 天 5267 条、字节占比 57.9% 实证）。
            # 计数先行自增：聚合行 N＝自上次留痕以来的归因观测轮数（含本轮）。
            key = (
                tuple(sorted(str(p) for p in files)),
                str(session.get("identity") or ""),
            )
            self._attr_suppress_count += 1
            if key != self._last_session_attr:
                self._last_session_attr = key
                self._attr_suppress_count = 0
                self._attr_last_log_ts = now
                self._log(
                    "info",
                    f"主树散件 WIP 归因到主树活交互会话，降级 info 留痕（不派"
                    f" major 不触发 admin 代查）: {', '.join(files)}; "
                    f"{info.describe()}",
                )
            elif now - self._attr_last_log_ts >= 3600:
                self._log(
                    "info",
                    f"近 1h 重复归因 {self._attr_suppress_count} 次，归因未变: "
                    f"{', '.join(files)}",
                )
                self._attr_suppress_count = 0
                self._attr_last_log_ts = now
            return {
                "status": "session-attributed",
                "files": files,
                "fingerprint": fp,
                "session_signals": list(session.get("signals") or []),
            }
        # 落入无主流形的两种情况共用既有宽限升级流：真零命中，或会话归因被
        # 配置 keep 回退（视同零命中走现状行为——配置事故/人工回退保守方向）。
        if session_attributed:
            # keep 回退注记按 60 分钟窗聚合（与 2.1 三态留痕同题同纪律）：
            # 配置 keep 且散件持续被归因时不再逐轮重写同一行，配置事故日志
            # 量由线性放大变有界。
            if now - self._keep_fallback_tracked_ts >= 3600:
                self._keep_fallback_tracked_ts = now
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

    def _release_session_attr_if_gone(
        self, session_attributed: bool, files: list
    ) -> None:
        """会话归因解除单点判定（evo-maintree-stray-attribution-log-dedup 1.3）。

        上轮已留痕而本轮归因不在场（not session_attributed 或 files 为空）→
        补一条解除行并清去重状态（``_last_session_attr`` 置空、抑制计数清
        零）；解除后同会话再归因键与解除前同值，因键已清判「与上次不同」，
        自然按首次落全量行（R3 闭环，防被抑制计数吞掉）。files 为空的 clean
        早退到不了归因分支，该分支以 ``session_attributed=False`` 先行调用
        （文件消失迁移）；调用点共两处，判定条件单点在本方法。
        """
        if self._last_session_attr is None:
            return
        if session_attributed and files:
            return
        self._log(
            "info",
            "主树散件 WIP 会话归因解除（文件集消失/占用者清空/归因迁移，"
            f"去重状态复位）: {', '.join(self._last_session_attr[0])}",
        )
        self._last_session_attr = None
        self._attr_suppress_count = 0

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
        self,
        status_stdout: "str | None" = None,
        detail: "dict[str, str] | None" = None,
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
            detail: 已取回的 check-ignore 批量明细（``_git_check_ignore_detail``
                返回形态）——``_sweep_locked`` 内 untracked 流与白名单脱落流
                共用同一次 check-ignore 查询（同命令只跑一遍）；缺省 None 时
                自行查询（独立调用形态保持可用）。

        git 查询失败返回 None（调用方按放弃本轮处置，条目保留）。check-ignore
        以 --stdin 批量一次调用（散件多时避免逐路径子进程）；``-n
        --non-matching`` 保证每个输入路径都有输出行（未匹配输出 ``::\t路径``），
        按输出末列回映射、不依赖行序。
        """
        if status_stdout is None:
            status_stdout = self._git("status", "--porcelain", "-uall")
            if status_stdout is None:
                return None
        paths = _porcelain_untracked_paths(status_stdout)
        if not paths:
            return []
        if detail is None:
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
                    # -c core.quotePath=false（code-review item 17e26b92199c）：
                    # 非 ASCII 路径回显原样（与 porcelain 解析 + _unquote_git_path
                    # 的口径对齐），否则回显带引号 C 转义形、末列回映射恒失配。
                    "-c", "core.quotePath=false",
                    "check-ignore", "-v", "-n", "--non-matching", "--stdin",
                ],
                input="\n".join(paths) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
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

    def _untracked_signal(self, entries: list, running_run_ids=()) -> dict:
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

        越阈归因探测（evo-stray-untracked-session-attribution 1.1）：越过
        阈值后、宽限判定前调用 ``identify_wip_occupant``（与 tracked 流同一
        归因器、同一判据），命中即复位宽限计时、降级留痕、不升级——交互
        会话在写的 untracked WIP 不再与真散件同流；低于阈值早退分支不调用
        归因器（零子进程开销）。

        Args:
            entries: untracked 散件路径清单。
            running_run_ids: 在飞 run_id 列表，透传给越阈后的归因探测（与
                tracked 流同一入参口径；低于阈值时不消费）。

        Returns: 子 dict（并入 sweep 返回的 ``untracked`` 键）：status 取
        ``below-threshold`` / ``timed`` / ``alerted`` / ``escalated`` /
        ``session-attributed`` / ``holder-attributed``（后两个归因命中态
        复位计时、不进宽限告警与升级判定）。
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
                # 双档标记建条即占位（evo-persist-stray-escalation 1.1：
                # 持久化条目与内存条目同构，空串＝未标记）。
                "escalated_signal_at": "",
            }
            self._untracked_registry[fp] = entry
        else:
            # 指纹不变沿用原 first_seen（与 tracked 流 D1 同款：不归零重计）；
            # 仅刷新文件快照供告警 evidence 取最新清单。
            entry["files"] = list(entries)
        self._reset_untracked_registry_absent({fp})

        # 首现判定（evo-stray-first-sight-prevention 1.1）：插桩在
        # below_threshold 早退**之前**——低于 entry 阈值的目录型集合同样
        # 提示（below_threshold 静默缺口正是本判定的填补对象）；与既有
        # 阈值/宽限/升级判定完全解耦（提示不启动升级时钟、不改 status
        # 语义，两个返回分支共带 ``first_sight`` 子 dict 供消费方取用）。
        first_sight = self._untracked_first_sight(entries)

        if below_threshold:
            return {
                "status": "below-threshold",
                "files": list(entries),
                "count": count,
                "threshold": threshold,
                "fingerprint": fp,
                "first_sight": first_sight,
            }
        # 越阈归因探测（evo-stray-untracked-session-attribution 1.1）：命中
        # （会话归因 / 在飞车道 holder）即复位计时并返回命中态，本轮不进宽限
        # 告警与升级判定；零命中（含 keep 回退）返回注记，维持现状宽限升级
        # 流，注记随升级 evidence 下发供 admin 处置侧判读。
        attributed, attribution_note = self._untracked_attribution_probe(
            entries, fp, threshold, running_run_ids
        )
        if attributed is not None:
            return attributed
        grace = grace_minutes(self._config)
        elapsed_min = (now - entry["first_seen"]) / 60.0
        # 体积采集（evo-stray-untracked-escalation 1.1）：越过阈值后在册集合
        # 每轮 stat 级采集体积（design 成本 containment：不在全量散件上每轮
        # du——entry 阈值门控后在册集合规模小，stat 成本可负担）。采集独立于
        # 滞留时长：MUST NOT 以 elapsed 达标为体积计算前置（否则体积超限的
        # 集合被额外门控在 24h 之内，与「elapsed 或体积」的或语义相抵）。
        sizes = self._untracked_entry_sizes(entries)
        total_bytes = sum(sizes.values())
        entry["sizes_bytes"] = sizes
        entry["total_bytes"] = total_bytes
        alerted = False
        if elapsed_min >= grace and not entry.get("escalated_at"):
            if self._write_untracked_alert(entry, fp, threshold, grace, elapsed_min):
                entry["escalated_at"] = self._iso(now)
                alerted = True
        # 第二档升级判定（1.2）：滞留时长 ≥24h 或集合体积 ≥阈值，或语义——
        # 两路径每轮独立评估、互不为前置；双档标记（escalated_signal_at）
        # 保证同一集合只升级一次（AdminStore 拒写不计标记，下轮重试）。
        size_threshold = untracked_stray_size_threshold_bytes(self._config)
        stale_hit = elapsed_min >= UNTRACKED_ESCALATION_STALE_MINUTES
        size_hit = total_bytes >= size_threshold
        escalation_fired = False
        if (stale_hit or size_hit) and not entry.get("escalated_signal_at"):
            if self._write_untracked_escalated_alert(
                entry, fp, threshold, total_bytes, size_threshold,
                elapsed_min, stale_hit, size_hit,
                attribution_note=attribution_note,
            ):
                entry["escalated_signal_at"] = self._iso(now)
                escalation_fired = True
        return {
            "status": (
                "escalated" if escalation_fired
                else ("alerted" if alerted else "timed")
            ),
            "files": list(entries),
            "count": count,
            "threshold": threshold,
            "fingerprint": fp,
            "first_seen_iso": entry["first_seen_iso"],
            "grace_minutes": grace,
            "elapsed_minutes": round(elapsed_min, 3),
            "total_bytes": total_bytes,
            "size_threshold_bytes": size_threshold,
            "escalated_signal": bool(entry.get("escalated_signal_at")),
            "first_sight": first_sight,
        }

    def _untracked_attribution_probe(
        self, entries: list, fp: str, threshold: int, running_run_ids=()
    ) -> "tuple[dict | None, str]":
        """untracked 越阈集合的会话归因探测（evo-stray-untracked-session-attribution）。

        与 tracked 流同一归因器（``identify_wip_occupant``）、同一判据（近窗
        提交路径交/活跃 transcript 路径提及）。返回 ``(命中处置, 升级注记)``，
        归因器三态各自约定处置、无未定义态：

        - 命中会话归因且 ``admin.maintree_session_attribution_action != keep``
          （缺省 info）：pop 计时条目（宽限时钟复位——复位而非永久豁免，会话
          离场后 re-建档自然重新起算）、info 留痕，返回 ``(session-attributed
          结果, "")``；
        - 命中在飞实现车道 holder（非会话归因；机制可达：车道分支 git add 了
          与主树 untracked 同名的路径后三点 diff 与集合求交命中）：同样 pop
          计时、不告警，返回 ``(holder-attributed 结果, "")``——对齐 tracked
          流 holder 分支「归属期间不算滞留」，MUST NOT 视同零命中走宽限升级
          （否则对仍在飞 run 名下的文件发射 major）；
        - 零命中：返回 ``(None, 零命中注记)``，维持现状宽限升级流；
        - 命中会话归因但配置 keep：返回 ``(None, keep 回退注记)``，视同零命中
          （注记 MUST NOT 误述为零命中，误导 admin 判读）；
        - 归因器缺失：返回 ``(None, 未执行注记)``，fail-open 维持现状流（与
          主树会话探测「源缺失回无主」同方向，升级仅告警、误判影响有界）。

        pop 单独执行即可（absent 复位语义是清除「消失」指纹，pop 不属消失态
        ——由调用点的 ``_reset_untracked_registry_absent`` 在建档后处理），
        下轮指纹重建档 first_seen 重起即「复位时钟」；持久化注册表收尾落盘
        镜像自然不含被 pop 条目，无需额外落盘处理。
        """
        identify = getattr(self.worktree_manager, "identify_wip_occupant", None)
        if not callable(identify):
            self._log(
                "warning",
                "untracked 散件归因探测跳过（identify_wip_occupant 不可用；"
                "fail-open 维持现状宽限流）",
            )
            return None, "归因探测未执行（归因器不可用，维持现状宽限流）"
        info = identify(entries, list(running_run_ids or []))
        session_attributed = info.holder and info.is_session_attribution()
        if info.holder and not session_attributed:
            self._untracked_registry.pop(fp, None)
            return {
                "status": "holder-attributed",
                "files": list(entries),
                "count": len(entries),
                "threshold": threshold,
                "fingerprint": fp,
                "holder_run_ids": info.holder_run_ids(),
            }, ""
        if session_attributed and session_attribution_action(self._config) != "keep":
            # 降级 info 留痕（与 tracked 流会话归因分支同型）：pop 计时条目；
            # 留痕走既有日志通道，MUST NOT 新增 AdminStore signal_type（免
            # admin_monitor 三表登记缺口——漏登记则落 store 后无人摄取）。
            self._untracked_registry.pop(fp, None)
            session = next(iter(info.holders), {}).get("session") or {}
            self._log(
                "info",
                f"主树 untracked 散件归因到主树活交互会话，复位宽限计时（不"
                f"升级不处置）: {', '.join(entries)}; {info.describe()}",
            )
            return {
                "status": "session-attributed",
                "files": list(entries),
                "count": len(entries),
                "threshold": threshold,
                "fingerprint": fp,
                "session_signals": list(session.get("signals") or []),
            }, ""
        if session_attributed:
            # keep 回退守卫与 tracked 流同键（运维心智单一）：视同零命中走
            # 无主宽限升级，注记如实区分「命中但回退」与「零命中」。注记为
            # 静态文案，按 60 分钟窗聚合（与 tracked 流回退注记同款纪律），
            # 不再逐轮重写同一行；返回值不受门控（探测三态契约不变）。
            if time.time() - self._keep_fallback_untracked_ts >= 3600:
                self._keep_fallback_untracked_ts = time.time()
                self._log(
                    "info",
                    "untracked 散件会话归因按 "
                    "admin.maintree_session_attribution_action=keep 回退现状行为"
                    "（视同零命中走无主宽限升级）",
                )
            return None, "归因探测已执行，命中但配置 keep 回退（视同零命中）"
        return (
            None,
            "归因探测已执行，零命中（判据：近窗提交路径交/活跃 transcript "
            "路径提及）",
        )

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

    def _untracked_entry_sizes(self, entries: list) -> dict:
        """逐 entry 体积（字节，evo-stray-untracked-escalation 1.1）：stat 级
        读元数据，不读内容。

        不可读（竞态删除/权限）按 0 计——体积是升级判定的增强数据源，单条目
        不可读 MUST NOT 放大成本轮放弃（与指纹的 unreadable 占位语义不同：
        指纹占位参与哈希使下轮自然重计，体积只参与阈值比较）。
        """
        sizes: dict = {}
        for rel in entries:
            try:
                sizes[str(rel)] = (self.project_root / rel).stat().st_size
            except OSError:
                sizes[str(rel)] = 0
        return sizes

    def _reset_untracked_registry_absent(self, current_fingerprints: set) -> None:
        """清除指纹不再出现的 untracked 注册表条目（指纹消失自动复位）。"""
        for fp in [
            k for k in self._untracked_registry if k not in current_fingerprints
        ]:
            del self._untracked_registry[fp]

    # ── untracked 首现提示（evo-stray-first-sight-prevention 1.1/1.2）────

    def _untracked_first_sight(self, entries: list) -> dict:
        """目录型产物集合首现判定与一次性 info 提示（1.1/1.2）。

        归组（``_untracked_first_sight_groups``）后逐目录判定：首现登记无
        该目录记录即发一次 maintree_untracked_stray_first_sight（建议面，
        不自动 ignore、不升级不唤起）；登记命中仅刷新条目快照——同目录
        仅提示一次，集合内容增长（条目增删/跨阈值档指纹漂移）不视为新
        首现。复位判据＝目录整轮不再贡献散件条目（同 absent 复位模式），
        复位后再现视为新首现。

        Returns: 子 dict（并入 ``_untracked_signal`` 返回的 ``first_sight``
        键）：status 取 ``prompted`` / ``clean`` / ``abandoned``（归组查询
        不可用时放弃本轮首现判定——登记不动、不提示，既有阈值流不受影响）。
        """
        grouped = self._untracked_first_sight_groups(entries)
        if grouped is None:
            return {"status": "abandoned"}
        now = time.time()
        prompted: list = []
        for dir_path in sorted(grouped):
            group = grouped[dir_path]
            entry = self._first_sight_dirs.get(dir_path)
            if entry is not None:
                # 同目录仅提示一次：只刷新快照（兼供收尾落盘取最新清单），
                # 内容增长不重提示。
                entry["files"] = list(group)
                continue
            sizes = self._untracked_entry_sizes(group)
            total_bytes = sum(sizes.values())
            if self._write_first_sight_alert(dir_path, group, total_bytes):
                self._first_sight_dirs[dir_path] = {
                    "first_seen": now,
                    "first_seen_iso": self._iso(now),
                    "files": list(group),
                }
                prompted.append(dir_path)
            # 拒写不计首现登记（下轮重试），同「不让提示静默蒸发」口径。
        self._reset_first_sight_registry_absent(set(grouped))
        return {
            "status": "prompted" if prompted else "clean",
            "dirs": sorted(grouped),
            "prompted": prompted,
        }

    def _untracked_first_sight_groups(
        self, entries: list
    ) -> "dict[str, list[str]] | None":
        """按「目录型产物集合的规范化根目录」归组散件条目（1.1 归组约定）。

        既有盘点无归组，本判定新增：对每个含目录成分的散件条目，取其
        **最浅的全 untracked 祖先目录**为规范化根目录（即「新建产物目录」
        ——不含任何 tracked 文件的目录；git 不跟踪目录本身，以「目录下
        无索引文件」为机械判据）；同一根目录下的条目归为一个集合。两类
        形态不在首现面、仍走既有阈值流：顶层散文件（无目录成分，如历史
        上入库的 build-win-configure.log 形态），与全部祖先目录都含 tracked
        文件的散件（落在既有目录内的散文件，如源码目录里的临时笔记——
        对其建议整目录 ignore 会误伤 tracked 文件）。

        Returns: 根目录 → 条目清单（相对路径，排序不保证，发射侧 sorted）；
        ``git ls-files`` 不可用返回 None（调用方按放弃本轮首现判定处置）。
        无任何目录型候选时返回空 dict（零子进程开销）。
        """
        candidates = [str(e) for e in entries if "/" in str(e)]
        if not candidates:
            return {}
        indexed = self._git_indexed_paths()
        if indexed is None:
            return None
        # 索引目录前缀集一次构建（O(索引规模×路径深度)）：判据「目录下无
        # tracked 文件」＝该目录前缀不在集合中，避免逐候选目录全索引扫描。
        tracked_dirs: set = set()
        for p in indexed:
            parts = p.split("/")
            for i in range(1, len(parts)):
                tracked_dirs.add("/".join(parts[:i]))
        groups: dict = {}
        for raw in candidates:
            parts = raw.split("/")
            root = None
            for i in range(1, len(parts)):
                ancestor = "/".join(parts[:i])
                if ancestor not in tracked_dirs:
                    root = ancestor  # 最浅全 untracked 祖先＝规范化根目录
                    break
            if root is None:
                continue  # 全部祖先含 tracked 文件＝既有目录内散文件
            groups.setdefault(root, []).append(raw)
        return groups

    def _reset_first_sight_registry_absent(self, current_dirs: set) -> None:
        """清除本轮不再贡献散件条目的首现登记（同 absent 复位模式，1.2）。

        复位后再现视为新首现（复发场景正是提示价值所在）；调用点两处：
        ``_untracked_first_sight`` 收尾（含当轮目录集）与 ``_sweep_locked``
        零散件早退（空集＝全部目录都不再贡献）。
        """
        for d in [k for k in self._first_sight_dirs if k not in current_dirs]:
            del self._first_sight_dirs[d]

    def _write_first_sight_alert(
        self, dir_path: str, entries: list, total_bytes: int
    ) -> bool:
        """目录型产物集合首现一次性 info 提示（经 AdminStore.append 落盘）。

        ``signal_type=maintree_untracked_stray_first_sight``：admin_monitor
        仅两表登记（SIGNAL_SEVERITY=info / SIGNAL_RECOMMENDATION），MUST
        NOT 收录 STORED_SIGNAL_TYPES（不自动唤起 admin run）。evidence 携带
        条目清单、总体积与预防性 .gitignore 条目草案（含成因注释，对齐
        913f41b/151ff6e 预防性 ignore 先例的注释风格）。建议面语义：不自动
        执行 ignore 动作（盘点零写副作用）。AdminStore 拒写时返回 False
        （不计首现登记，下轮重试），不让提示静默蒸发。
        """
        from core.admin_store import AdminStore, SIGNAL

        files = list(entries)
        draft_line = f"{dir_path}/"
        draft_comment = (
            f"主树 untracked 散件首现自动起草：运行时产物目录，"
            f"{len(files)} 个未跟踪 entry（{int(total_bytes)} 字节）滞留，"
            "预防性 ignore 后不再产生散件告警"
        )
        evidence = (
            f"项目名={self.project_root.name}; "
            f"目录集合={dir_path}; "
            f"条目数={len(files)}; 体积合计={int(total_bytes)}字节; "
            f"文件清单({len(files)}): {', '.join(files) or '无'}; "
            f"gitignore草案: {draft_line}（成因注释: {draft_comment}）; "
            f"豁免注记: .fenix/ negation 放行项与已 ignore 路径不计入"
            f"（本集合未被 .gitignore 覆盖，否则不入散件清单）; "
            f"零触碰注记: 本盘点只读（未执行 stash/checkout/clean/reset），"
            f"提示发出前后主树工作区状态未变"
        )
        store = AdminStore(self.project_root, logger=None)
        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE,
                "spec": None,
                "severity": "info",
                "description": (
                    "主树 untracked 散件首现提示（周期盘点，info 级只提示"
                    f"不处置）：目录型产物集合 {dir_path} 首次出现 "
                    f"{len(files)} 个 untracked entry。同目录仅提示一次"
                    "（集合内容增长不重提示），目录消失复位后再现视为新"
                    "首现；本提示不启动升级时钟、不派生任何自动处置，仅"
                    "建议预防性 ignore"
                ),
                "evidence": evidence,
                "source": "maintree-stray-wip-sweep",
                "recommended_action": (
                    "建议面（info 级只提示不处置，不唤起人工）：人工核对"
                    "目录归属后，将 evidence 中 gitignore 草案行（含成因"
                    "注释）追加至 .gitignore（预防性 ignore，一行消除该"
                    "目录后续散件告警），或将默认落盘路径移出仓库树/挪入"
                    "证据落位目录 .fenix/verify-evidence/<spec>/；本提示"
                    "不自动执行 ignore 动作（ignore 仍走既有裁决执行器或"
                    "人工）。同目录仅提示一次，目录消失复位后再现视为新"
                    "首现"
                ),
            }
        )
        if rec is None:
            self._log(
                "warning",
                f"{UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE}: 提示写入被拒"
                f"（AdminStore 拒写），未落盘——本轮不计首现登记，下轮盘点"
                f"重试",
            )
            return False
        self._log(
            "info",
            f"{UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE}: 目录型产物集合首现提示"
            f"（{len(files)} entry / {int(total_bytes)} 字节，gitignore 草案: "
            f"{draft_line}）已发一次性 info 提示: {', '.join(files)}",
        )
        return True

    # ── untracked 注册表持久化（evo-persist-stray-escalation 1.1/1.2）────

    def _untracked_registry_path(self) -> Path:
        """注册表持久化文件落点（.fenix/ 运行时状态区，见模块常量注记）。"""
        return self.project_root / UNTRACKED_REGISTRY_RELPATH

    def _load_untracked_registry(self) -> None:
        """盘点开始时载入持久化注册表（每进程一次），重启恢复时钟。

        文件缺失＝首启/无历史（正常形态，空表起步不告警）；损坏容错覆盖
        字节层与 JSON 层两类（半截写入/磁盘错误的典型损坏形态）：字节层
        （非法 UTF-8，``read_text`` 解码即抛 ``UnicodeDecodeError``）与
        JSON 层（坏 JSON/形态非法，``json.loads`` 抛 ``ValueError``/
        ``TypeError``）均回退空表并留一条告警（fail-open，不阻断主盘点
        ——损失仅为重新宽限，与 D5 决策被取代前的重启行为一致）。条目级
        形态守卫：非 dict 指纹段 / 缺 first_seen 数值 / files 非列表的
        条目剔除（部分损坏不株连完好条目）。载入后内存态为单源
        （``_untracked_registry_loaded`` 守卫），文件此后只是收尾落盘的
        镜像。
        """
        if self._untracked_registry_loaded:
            return
        self._untracked_registry_loaded = True
        path = self._untracked_registry_path()
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except (OSError, UnicodeDecodeError) as exc:
            # UnicodeDecodeError 是 ValueError 子类、非 OSError，须显式列出
            # 才能在 json.loads 之前拦住字节层损坏（evo 验证 BUG-01）。
            self._log(
                "warning",
                f"untracked 注册表持久化文件读取失败或字节层损坏，回退空表"
                f"重新宽限（fail-open，不阻断主盘点）: {path}: {exc}",
            )
            return
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError(f"registry payload is not an object: {type(data)}")
            # 分区适配（evo-stray-first-sight-prevention 1.2，读写同步）：新版
            # 顶层两分区（untracked 指纹注册表 / first_sight_dirs 目录键首现
            # 登记）；旧版扁平形态（顶层即指纹→条目）按 legacy 整体归入
            # untracked 分区，首现登记空表起步。
            if (
                _UNTRACKED_SECTION_KEY in data
                or _FIRST_SIGHT_SECTION_KEY in data
            ):
                untracked_raw = data.get(_UNTRACKED_SECTION_KEY) or {}
                first_sight_raw = data.get(_FIRST_SIGHT_SECTION_KEY) or {}
                if not isinstance(untracked_raw, dict) or not isinstance(
                    first_sight_raw, dict
                ):
                    raise ValueError(
                        "registry sections must both be objects: "
                        f"{type(untracked_raw)}/{type(first_sight_raw)}"
                    )
            else:
                untracked_raw, first_sight_raw = data, {}
            restored: dict = {}
            for fp, item in untracked_raw.items():
                if not isinstance(item, dict):
                    continue
                first_seen = item.get("first_seen")
                files = item.get("files")
                if not isinstance(first_seen, (int, float)) or not isinstance(
                    files, list
                ):
                    continue
                entry = {
                    "first_seen": float(first_seen),
                    "first_seen_iso": str(
                        item.get("first_seen_iso") or self._iso(float(first_seen))
                    ),
                    "files": [str(p) for p in files],
                    "escalated_at": str(item.get("escalated_at") or ""),
                    "escalated_signal_at": str(
                        item.get("escalated_signal_at") or ""
                    ),
                }
                restored[str(fp)] = entry
            restored_dirs: dict = {}
            for d, item in first_sight_raw.items():
                if not isinstance(item, dict):
                    continue
                first_seen = item.get("first_seen")
                files = item.get("files")
                if not isinstance(first_seen, (int, float)) or not isinstance(
                    files, list
                ):
                    continue
                restored_dirs[str(d)] = {
                    "first_seen": float(first_seen),
                    "first_seen_iso": str(
                        item.get("first_seen_iso") or self._iso(float(first_seen))
                    ),
                    "files": [str(p) for p in files],
                }
        except (ValueError, TypeError) as exc:
            self._untracked_registry = {}
            self._first_sight_dirs = {}
            self._log(
                "warning",
                f"untracked 注册表持久化文件损坏，回退空表重新宽限"
                f"（fail-open，不阻断主盘点）: {path}: {exc}",
            )
            return
        self._untracked_registry.update(restored)
        self._first_sight_dirs.update(restored_dirs)
        self._prune_untracked_registry_stale_paths()

    def _prune_untracked_registry_stale_paths(self) -> None:
        """惰性清理（1.2）：剔除盘上已消失路径，集合为空的指纹整条删除。

        载入时与每轮盘点收尾各执行一次，使历史路径不当作存活散件参与计时
        与升级（已归档/删除的散件处置后不复燃）。逐路径 ``exists()`` 探测
        开销与在册条目数线性（注册表规模小），不读内容。
        """
        root = self.project_root
        for fp in list(self._untracked_registry):
            entry = self._untracked_registry[fp]
            files = entry.get("files") or []
            alive = [p for p in files if (root / p).exists()]
            if len(alive) == len(files):
                continue
            if alive:
                entry["files"] = alive
            else:
                del self._untracked_registry[fp]

    def _persist_untracked_registry(self) -> None:
        """注册表变更时原子落盘（tempfile + os.replace，沿 core/signals.py
        既有原子写范式）。

        序列化结果与上次落盘 payload 逐字节相同即跳过（无变更不写盘）。
        顶层两分区（evo-stray-first-sight-prevention 1.2，与载入适配同步）：
        ``untracked``＝指纹注册表（``_UNTRACKED_PERSISTED_FIELDS`` 投影），
        ``first_sight_dirs``＝首现登记（``_FIRST_SIGHT_PERSISTED_FIELDS``
        投影，目录键）。sizes_bytes/total_bytes 等现采值不入。任何写盘失败
        仅告警（fail-open）：持久化缺失的代价是重启后重新宽限（D5 被取代
        前行为），MUST NOT 放大成本轮盘点失败。临时文件放同目录（os.replace
        原子换入）且以点前缀命名，避免被任何 ``*.json`` 扫描谓词命中并发
        写入中的半程文件。
        """
        payload = {
            _UNTRACKED_SECTION_KEY: {
                str(fp): {k: entry[k] for k in _UNTRACKED_PERSISTED_FIELDS
                          if k in entry}
                for fp, entry in self._untracked_registry.items()
            },
            _FIRST_SIGHT_SECTION_KEY: {
                str(d): {k: entry[k] for k in _FIRST_SIGHT_PERSISTED_FIELDS
                         if k in entry}
                for d, entry in self._first_sight_dirs.items()
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        if text == self._untracked_persisted_payload:
            return
        path = self._untracked_registry_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent),
                prefix=".stray_untracked_registry.json.tmp.",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            self._log(
                "warning",
                f"untracked 注册表持久化写入失败（fail-open，内存态不受影响，"
                f"重启后回退重新宽限）: {path}: {exc}",
            )
            return
        self._untracked_persisted_payload = text

    # ── 白名单脱落口径（evo-whitelist-tracked-patrol 1.1）────────────────

    def _whitelist_untracked_entries(
        self, paths: list, detail: "dict[str, str] | None"
    ) -> "list[str] | None":
        """白名单脱落候选清单：命中 ``!`` 放行规则且不在 git 索引中的路径。

        判定两段（design 1）：
        - ``detail``（check-ignore 批量明细，与 untracked 散件流共用同一次
          查询）筛出规则以 ``!`` 开头的放行路径——放行即「声明入库意图」的
          机械判据，零 .gitignore 自解析（与豁免①同一查询的镜像消费：
          散件流对放行项豁免不计，本流恰以放行项为检测目标，两流互不污染）；
        - ``git ls-files`` 全量索引一次取回求交，不在索引中的放行路径即脱落
          候选（design 明示的第二段确认查询：候选源当前仅 porcelain ``??``
          路径时两段判定天然同真，ls-files 求交保持判定自洽、不依赖候选源
          恰为 untracked 的前提）。

        Args:
            paths: porcelain ``??`` 候选路径（``_porcelain_untracked_paths``）。
            detail: check-ignore 批量明细（``_git_check_ignore_detail`` 形态）。

        ls-files 查询失败返回 None（调用方按放弃本流处置：不告警不复位，
        注册表条目保留交下轮——保守语义与 tracked/untracked 流同款）。
        """
        if detail is None:
            return None
        released = [
            p for p in paths if (detail.get(p) or "").startswith("!")
        ]
        if not released:
            return []
        indexed = self._git_indexed_paths()
        if indexed is None:
            return None
        return sorted(p for p in released if p not in indexed)

    def _git_indexed_paths(self) -> "set[str] | None":
        """``git ls-files -z`` 全量索引路径集（只读，一次子进程）。

        全量取回而非逐路径查询：ls-files 实参按 pathspec 语义解析（glob/
        ``:`` magic），直传文件名有误读风险；-z 输出无引号包装，与 porcelain
        反转义路径直接可比。仅在放行候选非空时才被调用（常态零开销）。
        """
        out = self._git("ls-files", "-z")
        if out is None:
            return None
        return {p for p in out.split("\0") if p}

    def _whitelist_signal(
        self, paths: list, detail: "dict[str, str] | None"
    ) -> dict:
        """白名单脱落信号流（evo-whitelist-tracked-patrol 1.1）。

        即时发射（无阈值无宽限——「放行+未跟踪＝异常」，脱落没有滞留容忍
        语义，c91213f 事故 6 天未察实证等待机制不可用）；去重沿用 untracked
        流同款指纹注册表口径（``_whitelist_registry`` 分账独立 + 同指纹只发
        一次 + 指纹消失自动复位），指纹取放行-未跟踪路径排序集 + 逐文件内容
        sha256（复用 ``_untracked_fingerprint``：untracked 不可复用 tracked
        ``git diff HEAD`` 指纹形态的同款论证适用）。只告警不处置：不自动执行
        git add 类修复动作，信号唤起人工/裁决二选一（恢复入库或删除放行规则）。

        Returns: 子 dict（并入 sweep 返回的 ``whitelist_untracked`` 键）：
        status 取 ``clean`` / ``alerted`` / ``recorded`` / ``abandoned``。
        """
        entries = self._whitelist_untracked_entries(paths, detail)
        if entries is None:
            # ls-files/check-ignore 明细不可用：放弃本流（不告警不复位，条目
            # 保留交下轮）；散件流与 tracked 流不受影响（各自判定已在前序
            # 步骤完成，互不污染）。
            self._log(
                "warning",
                "Whitelist patrol skipped (git inventory unavailable; "
                "conservative abandon, entries kept)",
            )
            return {"status": "abandoned"}
        if not entries:
            self._reset_whitelist_registry_absent(set())
            return {"status": "clean", "files": [], "count": 0}
        fp = self._untracked_fingerprint(entries)
        now = time.time()
        entry = self._whitelist_registry.get(fp)
        if entry is None:
            entry = {
                "first_seen": now,
                "first_seen_iso": self._iso(now),
                "files": list(entries),
                "rules": {},
                "escalated_at": "",
            }
            self._whitelist_registry[fp] = entry
        else:
            # 指纹不变沿用原 first_seen（与 tracked/untracked 流同款）；
            # 仅刷新文件与放行规则快照供告警 evidence 取最新清单。
            entry["files"] = list(entries)
        entry["rules"] = {
            p: (detail or {}).get(p, "") for p in entries
        }
        self._reset_whitelist_registry_absent({fp})
        alerted = False
        if not entry.get("escalated_at"):
            if self._write_whitelist_untracked_alert(entry, fp):
                entry["escalated_at"] = self._iso(now)
                alerted = True
        return {
            "status": "alerted" if alerted else "recorded",
            "files": list(entries),
            "count": len(entries),
            "fingerprint": fp,
            "first_seen_iso": entry["first_seen_iso"],
        }

    def _reset_whitelist_registry_absent(self, current_fingerprints: set) -> None:
        """清除指纹不再出现的白名单注册表条目（指纹消失自动复位）。"""
        for fp in [
            k for k in self._whitelist_registry if k not in current_fingerprints
        ]:
            del self._whitelist_registry[fp]

    # [fenix-ignore:83fec06ee6d1] 白名单流未执行归因探测、调用点 scope 内无可传注记，补段需给该流新增探测行为非最小修复（suggestion 自允维持现状）
    def _write_whitelist_untracked_alert(self, entry, fp) -> bool:
        """白名单脱落一次性 major 告警（经 AdminStore.append 落盘）。

        ``signal_type=whitelist_untracked``：admin_monitor 三表登记接入自动
        唤起（SIGNAL_SEVERITY=major / SIGNAL_RECOMMENDATION /
        STORED_SIGNAL_TYPES + 摄取项目名解析清单，对齐
        maintree_untracked_stray_escalated 先例）。evidence 含「项目名=」段
        （无 spec 形态摄取解析单源 evidence_project）与「文件清单(N):」段，
        另附放行规则快照（人工处置时免二次考古 .gitignore）。AdminStore 拒写
        时返回 False（escalated_at 不落、下轮重试），不让告警静默蒸发。
        """
        from core.admin_store import AdminStore, SIGNAL

        files = list(entry.get("files") or [])
        rules = entry.get("rules") or {}
        evidence = (
            f"项目名={self.project_root.name}; "
            f"first_seen={entry.get('first_seen_iso') or '?'}; "
            f"指纹={fp[:16]}; "
            f"文件清单({len(files)}): {', '.join(files) or '无'}; "
            f"放行规则: "
            f"{', '.join(f'{k}={v}' for k, v in sorted(rules.items())) or '无'}; "
            f"判定口径: negation 放行即声明入库意图，放行+未跟踪＝白名单脱落"
            f"（check-ignore -v 以 ! 规则命中且 git ls-files 不含该路径）; "
            f"计时口径: 内容指纹（放行-未跟踪路径排序集 + 逐文件内容 sha256）"
            f"——untracked 不进 git diff HEAD，不可复用 tracked 指纹形态; "
            f"豁免注记: 本信号不改变散件流豁免语义（放行项不计入散件，两流"
            f"分账）; "
            f"零触碰注记: 本盘点只读（未执行 stash/checkout/clean/reset/add），"
            f"告警发出前后主树工作区状态未变"
        )
        store = AdminStore(self.project_root, logger=None)
        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": WHITELIST_UNTRACKED_SIGNAL_TYPE,
                "spec": None,
                "severity": "major",
                "description": (
                    "白名单文件脱落（周期盘点，major）：negation 放行即声明"
                    f"入库意图，放行+未跟踪＝白名单脱落——{len(files)} 个被 "
                    ".gitignore ! 规则放行的路径不在 git 索引中，几乎必然是"
                    "脱落事故（入库意图已声明、文件却未入库，只能等 fresh "
                    "clone 或新开 worktree 断链才暴露）。本信号接入自动唤起，"
                    "等待人工二选一处置（恢复入库或删除放行规则），不自动"
                    "执行 git add 类修复动作"
                ),
                "evidence": evidence,
                "source": "maintree-stray-wip-sweep",
                "recommended_action": (
                    "negation 放行即声明入库意图，放行+未跟踪＝白名单脱落，"
                    "二选一处置：① git add 恢复入库（白名单状态文件应随仓库"
                    "入库，如 .fenix/verify.yaml / todo.md / "
                    "config.template.yaml）；② 删除 .gitignore 对应放行规则、"
                    "承认其为运行时文件（确保整体 ignore 规则覆盖）。文件清单"
                    "与放行规则见 evidence。同指纹一次性告警，指纹消失后盘点"
                    "状态自动复位"
                ),
            }
        )
        if rec is None:
            self._log(
                "warning",
                f"{WHITELIST_UNTRACKED_SIGNAL_TYPE}: 告警写入被拒"
                f"（AdminStore 拒写），未落盘——本轮不计升级标记，下轮盘点重试",
            )
            return False
        self._log(
            "warning",
            f"{WHITELIST_UNTRACKED_SIGNAL_TYPE}: 白名单文件脱落"
            f"（{len(files)} 个放行-未跟踪路径，"
            f"first_seen={entry.get('first_seen_iso')}）已发一次性 major 告警"
            f": {', '.join(files)}",
        )
        return True

    def _write_untracked_alert(self, entry, fp, threshold, grace, elapsed_min) -> bool:
        """untracked 散件滞留一次性 info 告警（经 AdminStore.append 落盘）。

        ``signal_type=maintree_untracked_stray_stale``：admin_monitor 仅两表
        登记（SIGNAL_SEVERITY=info / SIGNAL_RECOMMENDATION「只告警不处置」
        模板），**MUST NOT 收录 STORED_SIGNAL_TYPES**——摄取循环对收录类型
        无条件唤起、无 severity 过滤，收录即把 info 留痕升级为人工唤起
        （evo-stray-untracked-escalation 修订适用边界：info 信号维持不收录、
        升级信号除外）。可见性由 AdminStore 留痕与 Dashboard 承载；evidence
        含集合体积合计（1.1，逐条目体积随注册表 ``sizes_bytes`` 同源可查）。
        AdminStore 拒写时返回 False（escalated_at 不落、下轮重试），不让告警
        静默蒸发。
        """
        from core.admin_store import AdminStore, SIGNAL

        files = list(entry.get("files") or [])
        total_bytes = int(entry.get("total_bytes") or 0)
        evidence = (
            f"项目名={self.project_root.name}; "
            f"first_seen={entry.get('first_seen_iso') or '?'}; "
            f"滞留={round(elapsed_min, 1)}分钟; 宽限={grace:g}分钟; "
            f"阈值={threshold}个entry; 体积合计={total_bytes}字节; "
            f"指纹={fp[:16]}; "
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

    def _write_untracked_escalated_alert(
        self, entry, fp, threshold, total_bytes, size_threshold,
        elapsed_min, stale_hit, size_hit, attribution_note: str = "",
    ) -> bool:
        """untracked 散件第二档升级 major 告警（evo-stray-untracked-escalation）。

        ``signal_type=maintree_untracked_stray_escalated``：admin_monitor 三表
        登记接入自动唤起（SIGNAL_SEVERITY=major / SIGNAL_RECOMMENDATION /
        STORED_SIGNAL_TYPES + 摄取项目名解析清单）——info 前身信号「MUST NOT
        收录」裁定的显式修订载体（info 信号维持不收录、升级信号除外）。触发
        路径（滞留时长/体积，可双命中）随 evidence 下发；evidence 含「项目名=」
        段（无 spec 形态摄取解析单源 evidence_project）与「文件清单(N):」段
        （认领执行器清单单源，parse_stray_wip_manifest 同段级口径复用）。
        归因探测注记段（evo-stray-untracked-session-attribution 1.2）：措辞
        按探测结果分档（零命中 / 命中但配置 keep 回退），供 admin 处置侧判读
        归因探测已执行（对齐 tracked 流告警归因证据段形态）。
        AdminStore 拒写时返回 False（escalated_signal_at 不落、下轮重试），
        不让升级静默蒸发。
        """
        from core.admin_store import AdminStore, SIGNAL
        from core.dashboard.data.adjudication_choices import choices_for

        files = list(entry.get("files") or [])
        triggers = []
        if stale_hit:
            triggers.append(
                f"滞留时长≥{UNTRACKED_ESCALATION_STALE_MINUTES / 60:g}小时"
            )
        if size_hit:
            triggers.append(f"集合体积≥{size_threshold}字节")
        sizes = entry.get("sizes_bytes") or {}
        evidence = (
            f"项目名={self.project_root.name}; "
            f"first_seen={entry.get('first_seen_iso') or '?'}; "
            f"滞留={round(elapsed_min, 1)}分钟; "
            f"entry阈值={threshold}个; 体积合计={int(total_bytes)}字节; "
            f"体积阈值={size_threshold}字节; 指纹={fp[:16]}; "
            f"文件清单({len(files)}): {', '.join(files) or '无'}; "
            f"升级触发: {' + '.join(triggers) or '无'}; "
            f"条目体积(字节): "
            f"{', '.join(f'{k}={v}' for k, v in sorted(sizes.items())) or '无'}; "
            f"豁免注记: .fenix/ negation 放行项与已 ignore 路径不计入; "
            f"零触碰注记: 本盘点只读（未执行 stash/checkout/clean/reset），"
            f"告警发出前后主树工作区状态未变"
        )
        if attribution_note:
            evidence += f"归因探测: {attribution_note}; "
        store = AdminStore(self.project_root, logger=None)
        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": UNTRACKED_ESCALATED_SIGNAL_TYPE,
                "choices": list(choices_for(UNTRACKED_ESCALATED_SIGNAL_TYPE)),
                "spec": None,
                "severity": "major",
                "description": (
                    "主树 untracked 散件滞留升级（周期盘点第二档，major）："
                    f"{len(files)} 个 untracked entry（体积合计 "
                    f"{int(total_bytes)} 字节）滞留时长超 24 小时或集合体积"
                    "超阈值。本升级信号接入自动唤起，等待认领处置"
                    "（归档/追加 .gitignore/删除）"
                ),
                "evidence": evidence,
                "source": "maintree-stray-wip-sweep",
                "recommended_action": (
                    "核对主树这些 untracked 文件归属后，执行裁决选项 "
                    "archive_untracked_stray 显式归档（移入登记目录）、"
                    "ignore_untracked_stray 追加 .gitignore 或 "
                    "delete_untracked_stray 删除；文件清单、体积与滞留起点见 "
                    "evidence。同一集合只升级一次，指纹消失后盘点状态自动复位"
                ),
            }
        )
        if rec is None:
            self._log(
                "warning",
                f"{UNTRACKED_ESCALATED_SIGNAL_TYPE}: 升级告警写入被拒"
                f"（AdminStore 拒写），未落盘——本轮不计升级标记，下轮盘点重试",
            )
            return False
        self._log(
            "warning",
            f"{UNTRACKED_ESCALATED_SIGNAL_TYPE}: 主树 untracked 散件滞留升级"
            f"（{len(files)} entry / {int(total_bytes)} 字节，"
            f"触发: {' + '.join(triggers)}）已发一次性 major 升级告警: "
            f"{', '.join(files)}",
        )
        return True

    # ── 告警（core/code_fix._write_defer_orphan_alert 同型）─────────────

    def _prior_stray_rounds(self, files) -> int:
        """同文件历史 maintree_stray_wip_stale 告警/处置轮数（D2 复发计数）。

        evo-recurring-stray-remediation 2.1：以 AdminStore 既有 SIGNAL 记录
        为台账（design D2 不另建台账文件）——逐条解析 evidence「文件清单(N):」
        段（与 admin_actions.parse_stray_wip_manifest 同一段级口径，单源复用
        防 manifest 形态漂移后双处解析失配），与本次告警文件清单求交，非空即
        记一轮。store 不可读/解析链不可用按 0 处理——退化为「首次处置」语义，
        不阻断告警发射（复发检索是增强信息，不是告警门槛）。
        """
        if not files:
            return 0
        from core.admin_store import SIGNAL, AdminStore

        try:
            from core.dashboard.data.admin_actions import parse_stray_wip_manifest

            records = AdminStore(self.project_root, logger=None).read_all()
        except Exception:  # noqa: BLE001 — 复发检索失败不阻断告警发射
            return 0
        cur = {str(f) for f in files}
        rounds = 0
        for rec in records:
            if (rec.get("kind") != SIGNAL
                    or rec.get("signal_type") != SIGNAL_TYPE):
                continue
            if cur.intersection(parse_stray_wip_manifest(rec.get("evidence"))):
                rounds += 1
        return rounds

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
        # evo-recurring-stray-remediation 2.1：复发识别（design D2）——同文件
        # 历史 maintree_stray_wip_stale 告警/处置计数随 evidence 下发，使
        # 「第 2 度处置起必须根治」的义务在处置时点可判定，而非依赖 admin
        # 自行考古历史记录。
        prior_rounds = self._prior_stray_rounds(files)
        if prior_rounds >= 1:
            evidence += (
                f"; 复发注记: 同文件 maintree_stray_wip_stale 已 "
                f"{prior_rounds + 1} 度处置（历史告警/处置 {prior_rounds} 轮，"
                "本条为复发再告警）——复发型主树散件，第 2 度处置起 MUST 当场"
                "根治：执行裁决选项 untrack_stray_wip（git rm --cached 出库 + "
                ".gitignore 追加 + 独立提交，此后该路径改动由 ignore 规则自然"
                "吸收、不再产生散件告警）或等效操作，或在处置记录挂显式跟踪项"
                "（写明跟踪载体与复查时机）；MUST NOT 再以仅提交收尾"
            )
        store = AdminStore(self.project_root, logger=None)
        # evo-add-commit-stray-wip-choice 2.2：发射点快照 choices（照
        # mergeback.py 先例）。注册表为单源（缺键回退），告警是历史事实，
        # 注册表演进不回写历史告警的选项集。局部导入避免模块级环依赖。
        from core.dashboard.data.adjudication_choices import choices_for

        if prior_rounds >= 1:
            # 复发型：recommended_action 换根治优先口径（铁律义务随告警
            # 下发，administrator.md 铁律区同源约束）。
            recommended = (
                "复发型主树散件（同文件第 2 度处置起）：MUST 当场执行根治——"
                "执行裁决选项 untrack_stray_wip 一键出库（git rm --cached + "
                ".gitignore 追加 + 独立提交）或等效操作，或在处置记录挂显式"
                "跟踪项；MUST NOT 以仅提交第三次收尾。文件清单与复发计数见 "
                "evidence。同指纹一次性告警，改动消失后盘点状态自动复位"
            )
        else:
            recommended = (
                "人工核对主树这些未提交改动的归属后，提交（git add/commit）"
                "或 stash（git stash push）主树这些改动；或执行裁决选项 "
                "commit_stray_wip 一键提交信号清单内文件（与 stash 类动作"
                "互斥，处置记录附提交 hash）。文件清单与滞留起点见 "
                "evidence（worktree 分支型在飞车道之外的主树直改形态会被"
                "按无主升级，升级仅为告警）。同指纹一次性告警，改动消失后"
                "盘点状态自动复位"
            )
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
                "recommended_action": recommended,
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
