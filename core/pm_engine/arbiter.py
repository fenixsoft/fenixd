"""core/pm_engine/arbiter.py — 全局决策者车道（add-arbiter-lane）。

把「框架外验尸者」制度化：冻结→人类的升级边改道为
冻结→Arbiter→（大多数）自主处置 /（少数）带裁决包升级。

设计真相源：docs/superpowers/specs/2026-10-31-arbiter-lane-design.md
（fbeb3f104，含用户四项裁定：mode=full 立即执行、纯提示词红线、裁决包
挂原告警静默更新、自主处置零用户可感知告警）。

模块职责：
- 触发面（双咽喉改道）：state_machine.freeze_for_human 咽喉（经
  ``install_freeze_hook`` 回调解耦注册）与 pm_engine._send_human_escalation_alert
  （直接调 :meth:`ArbiterLane.submit_for_alert`）。
- 存量回扫（add-arbiter-backlog-sweep）：事件驱动的触发面对已发生的存量
  冻结无效（事件在 Arbiter 存在前已流过咽喉）——:meth:`ArbiterLane.sweep_on_startup`
  （daemon 启动后一次）与 :meth:`ArbiterLane.observe_enabled_transition`
  （config 热更新 disabled→enabled 跃迁时一次）补存量回扫，命中者走
  同一 dedup/单飞/预算管线，不建第二套派发路径。
- 触发面：freeze_spec（人工冻结）/mark_frozen_hold（簿记）/frozen_until
  （定时自愈赛跑）在 state_machine 侧零接触（不挂钩即排除）；signal 维度
  触发面为黑名单制（add-escalation-chain-admin-arbiter）——非黑名单即入
  链（含 token 预算耗尽 / spec_integrity 内容缺失 / queue 异常类，预算政
  策类由预算豁免拍板动作面承接），chain.blacklist 配置内信号直达人工队列。
- dedup：同 spec 同失败签名在飞只派发一次；处置成功后签名复发直接升级
  （design D6「处置后同根因复发」——失败不属复发，走死人开关连败计数）。
- 单飞：全局单飞队列串行——同一时刻至多一个 Arbiter run，后续触发排队；
  排队登记失败（队列满）MUST 显式报错，不吞 conflict 报假成功
  （scheduling_kick 单槽位「写侧吞 conflict 报假成功」前科规避）。
- 死人开关：同触发连败达 max_consecutive_failures（缺省 2）或单 run 超
  budget_wallclock_s/budget_tokens → 停止自主尝试、半成品调查包按挂靠
  语义升级，MUST NOT 静默死亡。
- 处置台账：五段结构（现场快照/取证时间轴/根因/处置动作或升级理由/证据
  回链）落 ``.fenix/arbiter_ledger.jsonl``。
- 告警零噪音分层：处置成功→原告警终态化 resolved_by=arbiter（不推送不进
  pending）；升级→同 alert_id 原位静默更新（报告进 narrative 槽位、choices/
  推荐注入原条目）并推 pending；两路径均不新增告警条目。
- 框架缺口路由（add-arbiter-gap-todo-routing）：立项通道已退役——调查报告
  gaps 数组逐条记 .fenix/todo.md（自省队列，走既有 todo 锁与结构契约，
  来源标记 arbiter+签名+run_id），由框架自进化车道按既有 todo 消费机制
  统一评估立项；切换窗旧 proposals 字段容错（WARNING 台账后丢弃）。

权限边界（用户裁定）：提示词红线+台账审计，不做机械强制——见
agents/arbiter.md 置顶红线段；本模块不建白名单动作执行器、不建 per-run
deny hooks（现状所有 agent 本就以 bypassPermissions spawn）。
"""

from __future__ import annotations

import json
import queue
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.agent_runner.lane_preflight import LanePreflightCache

# 日志组件名（logger.warning(component, message) 口径）
COMPONENT = "pm_engine.arbiter"

# ── 配置缺省（spec「配置与 Dashboard 设置页」四键）───────────────────────
ARBITER_ENABLED_DEFAULT = True
ARBITER_BUDGET_WALLCLOCK_S_DEFAULT = 1800
ARBITER_MAX_CONSECUTIVE_FAILURES_DEFAULT = 2
ARBITER_BUDGET_TOKENS_DEFAULT = 1_000_000
# infra 失败通道独立上限（harden-arbiter-lane-resilience 2.1）：缺省沿用
# judgment 连败上限同值（design §能力一「独立上限缺省同值」）。
ARBITER_MAX_CONSECUTIVE_INFRA_FAILURES_DEFAULT = (
    ARBITER_MAX_CONSECUTIVE_FAILURES_DEFAULT
)
# 派发前置探针结论 TTL（秒，agent-lane-preflight R3）：TTL 内复用探针结论，
# 超时重探——探针含 dsh --version 子进程探测，不能每触发都跑。
ARBITER_PREFLIGHT_TTL_DEFAULT = 300

# 触发面信号词表（freeze_for_human 词汇机械枚举基线）。signal 维度触发面
# 判定已反转为黑名单制（add-escalation-chain-admin-arbiter）：
# ``in_trigger_surface`` 只读 chain.blacklist 配置（缺省空集=全部升级边信号
# 默认入链；原白名单+排除表机制取消、排除表语义并入 blacklist 键——政策/
# 数据完整性/队列类不再硬编码排除，预算政策类由预算豁免拍板动作面承接）。
# 本词表保留作词汇机械枚举基线（tests/test_arbiter_lane.py::
# test_trigger_surface_covers_all_freeze_throat_signal_types 机械守卫钉死，
# 新增冻结族漏注册即红）。
# 词汇分裂教训（2026-11-01 两段修复）：单点锚定必是部分词汇——首版锚
# family.py 单点（verify_fail_escalation）漏 pipeline 争议族（evo-refine
# 回扫候选=0）；二版锚观测样本反向漏 family.py 与 spec-review 族
# （fix-planner 冻结未被接走，候选=1 派发=0 实证）。
ARBITER_TRIGGER_SIGNAL_TYPES = frozenset(
    {
        # ── freeze_for_human 九族（机械枚举在案，2026-11-01）──
        "verify_fail_escalation",     # family.py 冻结路径
        "verify_env_blocked",         # pipeline 争议/环境阻塞（evo-refine 实证）
        "spec-review-incomplete",     # spec_review 评审不完整（fix-planner 实证）
        "spec-review-rejected",       # spec_review 方案连续否决
        "judge_rerun_cap",            # judge 重跑上限（计数复位配方族）
        "verify_uniform_failure",     # 全场景同因失败
        "verifier_infra_death",       # 验证基础设施死亡
        # impl_budget_exhausted/spec_content_missing/redispatch_loop_detected
        # 三族不在本词表（黑名单制后默认即在触发面，无需登记）
        # ── 事件/回扫旁路名（非 freeze_for_human 直发）──
        "verdict_result_unreadable",  # pipeline 裁决缺失 fail-closed
        "blocked_stuck",              # admin_monitor blocked 超阈值未处理
        "manual-intervention",        # Administrator 处置请求（转人工边）
    }
)

# 遗留机器冻结菜单文案（2026-11-01 回扫机器证据第三半边）：标记字段
# （_frozen_source，freeze_for_human 写入）上线前的存量冻结标本，其 error
# 由框架冻结路径生成、内嵌「处置选项：①…②…」结构化菜单——人工冻结
# （freeze_spec）只写自由文本 reason，不含该菜单，据此回填分类。
ARBITER_LEGACY_MACHINE_FREEZE_MENU = "处置选项：①"

# 车道命名（runner 车道表同源：run_files.RUN_ID_AGENT_PREFIXES "arbiter-" 行）
ARBITER_RUN_PREFIX = "arbiter-"
# 调查报告实例文件（run 按 prompt 写入、框架读回后清理，admin 处置族同范式）
ARBITER_REPORT_PREFIX = "arbiter_report-"
# 处置台账（append-only JSONL；.fenix 运行时目录不入库）
ARBITER_LEDGER_FILENAME = "arbiter_ledger.jsonl"

# model 钉（design D9：narrative 车道 10-09 前科——不钉则踩 [1M] 别名秒挂）。
# agents.models.arbiter 已分配时用分配值；未分配时钉死本值，MUST NOT 回落
# 默认网关官方模型名。
ARBITER_PINNED_MODEL = "glm-5.3-flash"

# gap 记 todo 的落点小节（add-arbiter-gap-todo-routing）：自省 todo.md 的
# 「可改进」小节——evolution 解析侧只收集 TODO_SECTIONS 三值小节条目
# （浪费/失误/可改进），未知小节条目被跳过；gap 必须被自进化接手统一立项，
# 故落消费面可达的「可改进」，不落 knowledge_backfill 的 chores 登记小节。
# 形态与 self_review._append_todo 写入侧逐字一致（``### {section}``，:2061）：
# parse_todo_entries 的小节正则只认 ``### `` 前缀行，裸「可改进」不更新
# current_section → 条目 section 为空被收集面跳过（路由断链 + 自家 dedup
# 失灵）。
GAP_TODO_SECTION = "### 可改进"

# 单飞队列深度上限：决策点是低频高价值动作，深度 8 已远超正常积压；
# 满队列 = 显式报错（排队登记失败 MUST NOT 吞 conflict 报假成功）。
ARBITER_QUEUE_MAX = 8

# 复现升级在飞 dedup 窗口（秒，item 8a294f3ebdc2）：复现升级不经单飞队列、
# 不写 _active，同一冻结事件的双咽喉（冻结咽喉 alert_id=None 直派 → 告警
# 咽喉携 alert_id 补报，降级形态两咽喉必先后同到）对同签名会各自走完一次
# 复现判定——重复写台账并重复升级同一告警。窗口内第二报折叠为告警补绑
# （零台账）；两咽喉间隔为秒级事件对，窗口取宽裕值，超时自清不永久占用。
ARBITER_RECURRENCE_DEDUP_WINDOW_S = 120.0

# 台账条目五段结构键（spec「调查报告与处置台账」）：缺任一段即不完整。
LEDGER_SEGMENT_KEYS = (
    "scene_snapshot",     # 现场快照
    "forensic_timeline",  # 取证时间轴
    "root_cause",         # 根因
    "action_or_upgrade",  # 处置动作或升级理由
    "evidence_refs",      # 证据回链
)


def arbiter_failure_signature(spec: str, signal_type: str) -> str:
    """失败签名（dedup 键单源）：``<spec>::<signal_type>``。

    同一冻结/升级事件经双咽喉（freeze_for_human → _send_human_escalation_alert）
    各报一次时，两处按 (spec, signal_type) 计算出同签名——第二咽喉自然命中
    dedup（绑 alert 而非重复派发），无需跨模块传递事件 id。

    spec 成分中的 ``::`` 转义为 ``\\:\\:``（code-review 02f0a0197614）：裸
    拼接无转义时 spec="a::b"+signal="c" 与 spec="a"+signal="b::c" 产出同
    签名——本签名是 dedup、复现配额（chain 状态文件）、dead-man 台账、todo
    来源前缀的共用键，碰撞会把两个不同失败合并记账（误 dedup 吞掉一次升级、
    或配额被无关签名消耗）。转义序列自身不含连续 ``::``，故不含 ``::`` 的
    spec 逐字节不变——台账/配额/dead-man 存量键全部不受影响（不换分隔符、
    不做双格式迁移窗）。signal 侧为框架信号词表枚举名，不含 ``::``，不转义。
    """
    spec_part = (spec or "global").strip().replace("::", "\\:\\:")
    return f"{spec_part}::{(signal_type or 'unknown').strip()}"


def arbiter_report_path(project_root, run_id: str) -> Path:
    """Arbiter 调查报告实例文件路径（.fenix/arbiter_report-<run_id>.json）。

    prompt 注入侧与框架读侧同源（admin_disposition_path 先例：注入值 =
    读侧路径，防双实现漂移）。
    """
    return Path(project_root) / ".fenix" / f"{ARBITER_REPORT_PREFIX}{run_id}.json"


def arbiter_ledger_path(project_root) -> Path:
    """处置台账路径（.fenix/arbiter_ledger.jsonl，append-only）。"""
    return Path(project_root) / ".fenix" / ARBITER_LEDGER_FILENAME


def load_arbiter_ledger(project_root) -> List[dict]:
    """读全量处置台账（最新在后）。损坏行跳过（fail-open，不阻断读侧）。"""
    path = arbiter_ledger_path(project_root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    out: List[dict] = []
    # 9744fdf1cab7：按 \n 硬分割而非 splitlines()——写侧 append_run_line 的
    # json.dumps(ensure_ascii=False) 不转义 U+2028/U+2029，splitlines() 会按
    # 其边界拆行，含此类字符的台账条目（scene_snapshot 等最长 4000 字符的
    # 报告文本）裂成两个半行 JSON、双双解析失败被跳过——_ledger_sigs 读丢
    # dead-man/处置条目即跨重启配额豁免与 dead-man 永久例外失效、同签名被
    # 再次自主派发。落盘单行内唯一的真实换行即写侧追加的 \n，json 对 \r 等
    # 控制符恒转义；行尾 .strip() 兜住 \r\n。与
    # maintenance_ledger.list_maintenance_entries 读侧同款修复（code-review
    # item 34ace64df65c）。
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def ledger_entry_complete(entry: dict) -> bool:
    """台账条目五段完整性判定（spec「处置台账完整」验收口径）。"""
    if not isinstance(entry, dict):
        return False
    for key in LEDGER_SEGMENT_KEYS:
        val = entry.get(key)
        if val is None:
            return False
        if isinstance(val, str) and not val.strip():
            return False
        if isinstance(val, (list, tuple)) and not val:
            return False
    return True


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArbiterLane:
    """全局决策者车道单例（每项目一个）：触发面 / dedup / 单飞 / 死人开关。

    生命周期：``get_lane(project_root, logger)`` 惰性建单例（PMEngine 装配
    与 family.py 咽喉侧各取一次），运行时依赖再由装配方注入——
    :meth:`set_runner`（agent_runner）与 :meth:`set_state_machine`（engine.py
    装配点一并注入）；worker 线程懒启动（首个触发入队时拉起，daemon 线程
    不阻塞退出）。测试经 :func:`reset_lane` 清单例。
    """

    def __init__(self, project_root, logger=None):
        self.project_root = Path(project_root)
        self.logger = logger
        # RLock：submit 持锁内调 _bind_alert 会二次取锁（不可重入 Lock 死锁，
        # test_double_throat_single_dispatch_with_alert_bind 实测）——重入锁
        # 语义不变（同线程多次取放配平）。
        self._lock = threading.RLock()
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=ARBITER_QUEUE_MAX)
        self._worker: Optional[threading.Thread] = None
        # dedup/复发记账：在飞+排队中的签名（防双咽喉重复派发）；已自主处置
        # 成功过的签名（同签名处置后复发 → 直接升级，design D6「处置后同根因
        # 复发」——注意失败≠处置后复发，失败走死人开关重试计数）；已死人开关
        # 停机的签名（后续同签名触发直接升级，不再自主尝试）。
        self._active: set = set()
        self._dispositioned: set = set()
        self._deadmanned: set = set()
        # 死人开关：签名 → 连续失败计数（成功清零；连败达阈值→停止自主尝试）
        self._failure_counts: Dict[str, int] = {}
        # infra 失败通道（harden-arbiter-lane-resilience 2.1）：与 judgment
        # 连败计数完全分离的独立计数——基础设施故障（0 rounds/环境指纹）
        # 不烧死人开关资格，达上限也只记台账+告警不升级人工，健康探针
        # 成功（:meth:`on_lane_healthy`）即全量清零恢复自主处置资格。
        self._infra_failure_counts: Dict[str, int] = {}
        # 派发前置探针结论 TTL 缓存（agent-lane-preflight R3）：TTL 内复用
        # 探针结论零子进程开销，超时首查重探；TTL 热更新经 _preflight_gate
        # 重建（下次生效）。
        self._preflight_cache = LanePreflightCache(
            ARBITER_PREFLIGHT_TTL_DEFAULT
        )
        # 预算记账（贯穿 run 生命周期，验收「预算记账贯穿」）：run_id → 累计
        self._budget_ledger: Dict[str, dict] = {}
        # 在飞触发的迟到 alert 补绑表（签名 → alert_id；worker 取到触发时合并）
        self._pending_binds: Dict[str, str] = {}
        # 复现升级在飞标记（签名 → 单调时刻，窗口见
        # ARBITER_RECURRENCE_DEDUP_WINDOW_S）：复现升级不经队列/worker、
        # 无 _active 占位，同一冻结事件双咽喉的第二报在此命中 dedup
        # （item 8a294f3ebdc2）。
        self._recurrence_inflight: Dict[str, float] = {}
        # 存量回扫（add-arbiter-backlog-sweep 1.1）跃迁记账：
        # _startup_swept——启动回扫每进程至多一次（重复调用幂等短路）；
        # _last_seen_enabled——热更新跃迁观察基线（None=未观测，False→True
        # 跃迁时回扫一次；True→False 不回扫，下次 False→True 再回扫一次）。
        self._startup_swept = False
        self._last_seen_enabled: Optional[bool] = None
        # 派发前置探针拦截遥测（code-review d488eb0ddbeb）：拦截在返回字上
        # 与在飞 dedup 同字（零新契约的既有取舍）——累计计数供 snapshot()
        # 单列；拦截签名集供 sweep_backlog 把该形态从 deduped 摘要单列
        # preflight-blocked（派发成功或归类消费即清，防陈旧残留误标真
        # dedup；同签名已在飞的真 dedup 拦截不记入集合）。
        self._preflight_blocked_total = 0
        self._preflight_blocked_sigs: set = set()
        # 台账签名集读缓存（code-review fd762a606443）：台账 append-only
        # 无轮转，全量读盘解析成本随台账线性增长且在 submit_trigger 关键
        # 路径上——按（mtime_ns, size）失效缓存 (signature, kind) 投影，
        # 台账新写即整体失效重读（不持有全量记录 dict，内存只随签名数线性）。
        self._ledger_cache_key: Optional[tuple] = None
        self._ledger_sig_pairs: Optional[List[tuple]] = None

    # ── 配置读取（热更新语义：每次触发/run 读取时即时解析）─────────────

    def config(self) -> dict:
        """读取 arbiter 四键（经 ConfigLoader 单源，脏值回退缺省）。"""
        try:
            from core.config import ConfigLoader

            raw = ConfigLoader.resolve_config(self.project_root)
            return ConfigLoader.get_arbiter_config(raw)
        except Exception as e:  # 配置链故障不阻断车道装配判定（fail-open 关）
            self._log("warning", f"arbiter 配置读取失败（按关闭态降级）: {e}")
            return {
                "enabled": False,
                "budget_wallclock_s": ARBITER_BUDGET_WALLCLOCK_S_DEFAULT,
                "budget_tokens": ARBITER_BUDGET_TOKENS_DEFAULT,
                "max_consecutive_failures": ARBITER_MAX_CONSECUTIVE_FAILURES_DEFAULT,
                "max_consecutive_infra_failures": (
                    ARBITER_MAX_CONSECUTIVE_INFRA_FAILURES_DEFAULT
                ),
                "preflight_ttl": ARBITER_PREFLIGHT_TTL_DEFAULT,
            }

    @property
    def enabled(self) -> bool:
        return bool(self.config().get("enabled"))

    # ── 链配置/配额存取（add-escalation-chain-admin-arbiter 3.3）────────

    def _chain_cfg(self) -> dict:
        """链配置段读取（经链配额层单源；失败回空 dict=全缺省+空黑名单）。"""
        try:
            from core.pm_engine.escalation_chain import ChainQuotaStore

            return ChainQuotaStore(self.project_root, self.logger).quota_config()
        except Exception:
            return {}

    def _chain_quota(self):
        """链配额层实例（失败返回 None——配额判定按「配额未耗尽」fail-open）。"""
        try:
            from core.pm_engine.escalation_chain import ChainQuotaStore

            return ChainQuotaStore(self.project_root, self.logger)
        except Exception:
            return None

    def _arbiter_rulings_quota(self) -> int:
        """Arbiter 复现配额上限（chain.arbiter_rulings，缺省单源
        ConfigLoader.CHAIN_ARBITER_RULINGS_DEFAULT，现值 3）。"""
        from core.config import ConfigLoader

        try:
            default = ConfigLoader.CHAIN_ARBITER_RULINGS_DEFAULT
            return int(self._chain_cfg().get("arbiter_rulings") or default)
        except (TypeError, ValueError):
            # 兜底直接引用单源常量（对齐 escalation_chain.quota_config 口径，
            # 消除与缺省值的手工双份真相——该值 2026-11-03 刚经历 2→3 调整，
            # 硬编码 3 会在下次调值时静默漂移）
            return ConfigLoader.CHAIN_ARBITER_RULINGS_DEFAULT

    def _safe_rulings(self, quota, sig: str) -> int:
        """复现配额读侧容错（code-review 659188b1f8cc）：chain 状态文件
        局部损坏（signatures 内既有条目的 arbiter_rulings 字段被手工编辑
        成非数字）时 ChainQuotaStore.arbiter_rulings 内部 int() 抛
        ValueError——按 0（配额未耗尽）降级留 warning，不使触发登记与回扫
        扫描段整体中断（fail-open 方向与 _chain_quota 返回 None 同口径）。"""
        if quota is None:
            return 0
        try:
            return int(quota.arbiter_rulings(sig))
        except (TypeError, ValueError) as exc:
            self._log(
                "warning",
                f"arbiter 复现配额读侧值损坏（按 0 未耗尽降级）: sig={sig} {exc}",
            )
            return 0

    def in_trigger_surface(self, signal_type: str) -> bool:
        """signal 维度触发面判定（处置链反转后）：非黑名单即入。

        白名单+排除表机制被黑名单 kill switch 取代（add-escalation-chain-
        admin-arbiter）：``chain.blacklist`` 配置内的信号不进 Arbiter、也不进
        链（直达人工队列）；名单外信号默认在触发面（升级边默认自动化处置，
        政策类/数据完整性类人工兜底改由黑名单显式圈定）。黑名单经链配置单源
        （ConfigLoader.get_chain_config，热更新即时生效），读取失败按空名单
        fail-open（放行方向——历史白名单漏放信号的旧病不再以配置故障形态复发）。
        """
        sig = (signal_type or "").strip()
        blacklist = set(self._chain_cfg().get("blacklist") or [])
        return sig not in blacklist

    def _log(self, level: str, message: str, context: Optional[dict] = None):
        log = getattr(self, "logger", None)
        if log is None:
            return
        try:
            getattr(log, level)(COMPONENT, message, context or None)
        except TypeError:
            # logger 不支持 context 第三参时降级两参形态
            getattr(log, level)(COMPONENT, message)
        except Exception:
            pass

    # ── 触发面入口（双咽喉共用）───────────────────────────────────────

    def submit_trigger(
        self,
        *,
        spec: str,
        signal_type: str,
        severity: str = "major",
        description: str = "",
        evidence: str = "",
        recommended_action: str = "",
        alert_id: Optional[str] = None,
        source: str = "",
    ) -> str:
        """登记一次升级边触发（``submit_trigger``——命名避开泛用 ``submit``，防 fidelity 扫描把本方法当全仓 ``submit`` 唯一 seam、误挂测试侧 Executor 替身）。返回处置字：

        - ``"disabled"``：arbiter.enabled=false（关闭态零侵扰——调用方应走
          既有 narrative/人工路径，本方法不做任何写入）；
        - ``"excluded"``：signal 在 chain.blacklist 黑名单（留 narrative 与
          人类——不进 Arbiter 也不进链，直达人工队列）；spec 名路径不安全
          同出口（item dabef7963cec，与回扫面同款防线）；
        - ``"deduped"``：同签名已派发/在飞（含复现升级在飞）——本次触发
          只绑 alert/补挂告警升级，不再派发；**派发前置探针拦截
          （harden-arbiter-lane-resilience 3.2）同样返回本字**（零新契约，
          调用方零改动）——车道环境不可用时跳过本次派发且零状态变更
          （不写 _active、不消费复现标记、不落台账、不计配额），信号闭环
          靠既有触发面复报/回扫候选重扫自然回喂；
        - ``"recurrence-escalated"``：同签名已派发过（复发）——按 design D6
          直接产裁决包升级，不再自主处置；
        - ``"queued"``：已入单飞队列（排队后串行消费）。

        排队登记失败（队列满）抛 RuntimeError——显式报错，MUST NOT 报假成功
        （scheduling_kick 单槽位前科规避，design §15）。
        """
        cfg = self.config()
        if not cfg.get("enabled"):
            return "disabled"
        if not self.in_trigger_surface(signal_type):
            # 黑名单 kill switch 命中（触发面反转后 excluded=黑名单）：不进
            # Arbiter 也不进链，调用方走既有落盘路径（直达人工 + narrative）
            return "excluded"
        sig = arbiter_failure_signature(spec, signal_type)
        # 路径安全单点筛查（item dabef7963cec）：spec 名含 ../ 等不安全分量
        # 时签名会内插进 unfreeze/预算改写等写点，回扫面
        # （_backlog_candidates）已按同款排除；事件面（冻结/告警双咽喉）
        # 不安全即 excluded——不进 Arbiter 不进链不产生台账，调用方走既有
        # 落盘路径直达人工，与黑名单同出口。
        from core.pm_engine.verification.serving import _spec_name_path_error
        if _spec_name_path_error(spec):
            self._log(
                "warning",
                f"arbiter 触发拒绝路径不安全 spec={spec!r}",
            )
            return "excluded"
        # 拦截点位于一切 dedup/_recurrence_inflight 复现标记消费之前；命中
        # 零状态变更（见返回值段 deduped 条目注记）。关闭态零侵扰纪律下
        # disabled/excluded 先行短路（enabled=false 不派发不拦截不产生
        # 台账），探针只在真实派发意图上把关。拦截遥测（d488eb0ddbeb）：
        # 返回字保持 deduped（零新契约），车道级累计计数与拦截签名集单列
        # ——签名集供 sweep_backlog 把该形态从 deduped 摘要单列
        # preflight-blocked；同签名已在飞的触发即使被拦（探针复位后回扫
        # 重扫仍会 dedup），不记入集合防误标。
        if not self._preflight_gate():
            with self._lock:
                self._preflight_blocked_total += 1
                if sig not in self._active:
                    self._preflight_blocked_sigs.add(sig)
            return "deduped"
        # 跨重启配额判定（D6 单次纪律的配额制取代，add-escalation-chain-
        # admin-arbiter 3.3）：已自主处置次数 = 拍板计数（chain 配额状态文件
        # 持久化，跨重启有效）＋台账 dead-man 永久例外（单次停机不复位——
        # 「dead-man/停机类签名维持永久单次」）。配额未耗尽的签名复位窗/
        # 状态迁移清零由链配额层负责（此处只读判定，不复位不计数——拍板
        # 计数在 _on_disposition_success 落）。台账 dead-man 读失败按空集
        # fail-open（load_arbiter_ledger 自带降级）。
        # [fenix-ignore:e8ea683f7ae2] 配额/dead-man 读在锁外属本模块声明的慢盘取舍（单次超发有界、下一触发收敛）；严格化须把盘 IO 挪进 _lock 临界区，冻结咽喉热路径代价更大
        persisted_deadmanned = self._ledger_sigs(kinds={"dead-man"})
        quota = self._chain_quota()
        rulings = self._safe_rulings(quota, sig)
        rulings_cap = self._arbiter_rulings_quota()
        recurrence_payload: Optional[dict] = None
        recurrence_bind = False
        with self._lock:
            if sig in self._active:
                # 同签名在飞/排队：只绑 alert（原位挂靠目标），不重复派发
                if alert_id:
                    self._bind_alert(sig, alert_id)
                self._log(
                    "info",
                    f"arbiter 触发 dedup（同签名在飞/排队）: sig={sig} alert={alert_id}",
                )
                return "deduped"
            rec_at = self._recurrence_inflight.get(sig)
            if rec_at is not None and (
                time.monotonic() - rec_at > ARBITER_RECURRENCE_DEDUP_WINDOW_S
            ):
                # 窗口外自清：告警咽喉补报始终未到（store 拒写等告警未落盘
                # 形态）标记不永久占用——后续真实复发照常按配额语义上升
                self._recurrence_inflight.pop(sig, None)
                rec_at = None
            if rec_at is not None:
                # 同一冻结事件双咽喉第二报（复现升级在飞）：首次升级件已落
                # 台账（冻结咽喉 alert_id=None，当时告警未落盘），本次只补
                # 做告警原位升级、零台账落盘；携 alert_id 的补报即刻消费
                # 标记，锁外执行慢盘升级（与下方复发分支同纪律）。
                if alert_id:
                    self._recurrence_inflight.pop(sig, None)
                    recurrence_bind = True
                self._log(
                    "info",
                    f"arbiter 触发 dedup（复现升级在飞）: sig={sig} alert={alert_id}",
                )
                if not recurrence_bind:
                    return "deduped"
            elif (
                sig in self._deadmanned
                or sig in persisted_deadmanned
                or rulings >= rulings_cap
            ):
                # 复现配额耗尽 / dead-man 永久例外：不再自主处置，直接产裁
                # 决包升级（第 rulings+1 次复现强制上升——拍板 rulings/cap）
                self._log(
                    "warning",
                    f"arbiter 复现配额耗尽（{rulings}/{rulings_cap}）或 dead-man "
                    f"例外，跳过自主处置直接升级: sig={sig}",
                )
                # 锁内只暂存升级载荷（2cb4626ec8a3）：_record_recurrence_
                # escalation 的台账 append_run_line 与告警原位升级（AdminStore
                # + narrative sidecar）均为慢盘 IO，留在持锁关键区会拖慢并发
                # submit_trigger 与 snapshot（后者锁内经 self.enabled 读配置
                # 文件）。该方法不读锁内状态、输入全为传参，锁外执行不引入
                # 重入竞态。
                recurrence_payload = {
                    "spec": spec,
                    "signal_type": signal_type,
                    "sig": sig,
                    "severity": severity,
                    "description": description,
                    "evidence": evidence,
                    "alert_id": alert_id,
                    "rulings_used": rulings,
                    "rulings_cap": rulings_cap,
                }
                # 复现升级在飞登记（锁内，与 queued 分支 _active.add 同纪律）
                self._recurrence_inflight[sig] = time.monotonic()
            else:
                # worker 预热先于入队与 dedup 占位（c0f79d6b865f）：线程创建
                # /start 失败时队列未进、_active 未占，异常上抛即干净回滚，
                # 不留「队列条目无人消费 + 签名永久占用 dedup 集合」的失明
                # 残留（RLock：锁内调 _ensure_worker 同线程重入安全）。
                self._ensure_worker()
                trigger = {
                    "spec": spec,
                    "signal_type": signal_type,
                    "severity": severity,
                    "description": description,
                    "evidence": evidence,
                    "recommended_action": recommended_action,
                    "alert_id": alert_id,
                    "signature": sig,
                    "source": source,
                    "enqueued_at": _utcnow_iso(),
                    "budget": {
                        "wallclock_s": cfg.get("budget_wallclock_s"),
                        "tokens": cfg.get("budget_tokens"),
                    },
                }
                try:
                    self._queue.put_nowait(trigger)
                except queue.Full:
                    # 显式报错（不得吞 conflict 报假成功）：调用方按失败处理，
                    # 告警走既有 narrative/人工路径
                    raise RuntimeError(
                        f"arbiter 单飞队列已满（maxsize={ARBITER_QUEUE_MAX}），"
                        f"触发登记失败 spec={spec} signal={signal_type}"
                    )
                self._active.add(sig)
        if recurrence_payload is not None:
            self._record_recurrence_escalation(**recurrence_payload)
            return "recurrence-escalated"
        if recurrence_bind:
            # 同事件告警咽喉补报：只补做告警原位升级（首次触发已落台账），
            # 不重复写 recurrence-escalation 台账、不重复升级
            self._record_recurrence_escalation(
                spec=spec,
                signal_type=signal_type,
                sig=sig,
                severity=severity,
                description=description,
                evidence=evidence,
                alert_id=alert_id,
                rulings_used=rulings,
                rulings_cap=rulings_cap,
                write_ledger=False,
            )
            return "deduped"
        self._log(
            "info",
            f"arbiter 触发入队（单飞串行）: sig={sig} alert={alert_id} source={source}",
        )
        return "queued"

    def submit_for_alert(self, pm, entry: dict, alert_id: str) -> str:
        """_send_human_escalation_alert 咽喉入口（alert 落地后调用）。

        告警已落盘（alert_id 可用），升级包/终态化均可原位挂靠。
        """
        return self.submit_trigger(
            spec=str(entry.get("spec") or "global"),
            signal_type=str(entry.get("signal_type") or ""),
            severity=str(entry.get("severity") or "major"),
            description=str(entry.get("description") or ""),
            evidence=str(entry.get("evidence") or ""),
            recommended_action=str(entry.get("recommended_action") or ""),
            alert_id=alert_id,
            source="escalation-alert",
        )

    # ── 存量回扫（add-arbiter-backlog-sweep 1.1）─────────────────────

    def sweep_on_startup(self) -> dict:
        """启动回扫入口：daemon 装配后调用一次（每进程至多一次）。

        ``arbiter.enabled=true`` 时执行一次存量回扫并把 enabled 基线落位
        （此后热更新跃迁观察以此为起点）；enabled=false 时只落基线零扫描
        零写入（关闭态零侵扰，s8 同口径）。重复调用幂等短路（不再扫描）。
        """
        with self._lock:
            if self._startup_swept:
                return {"status": "already-swept", "source": "startup"}
            self._startup_swept = True
        enabled = self.enabled
        with self._lock:
            self._last_seen_enabled = enabled
        if not enabled:
            self._log("info", "arbiter 启动回扫跳过（enabled=false，仅落跃迁基线）")
            return {"status": "disabled", "source": "startup"}
        return self.sweep_backlog(source="startup")

    def observe_enabled_transition(self) -> dict:
        """热更新跃迁观察：config disabled→enabled 跃迁时回扫一次。

        由 30s 配置热更新周期调用（fenixd._maybe_reload_config 接线）。观测
        当次 enabled 与上次基线：False→True 跃迁 → 执行一次存量回扫；
        True→False / 无跃迁 / 基线未落位（None→True，启动态由
        sweep_on_startup 负责）→ 不回扫。每条跃迁至多回扫一次（基线随即
        更新），派发层幂等另由同签名 dedup 兜底。
        """
        enabled = self.enabled
        with self._lock:
            prev = self._last_seen_enabled
            self._last_seen_enabled = enabled
        if prev is False and enabled:
            self._log("info", "arbiter 检测到 disabled→enabled 热更新跃迁，执行存量回扫")
            return self.sweep_backlog(source="hot-reload")
        return {
            "status": "no-transition",
            "source": "hot-reload",
            "previous": prev,
            "current": enabled,
        }

    def snapshot(self) -> dict:
        """运行时只读快照：车道运行时面单帧视图（routes 读侧消费）。

        返回 dict 即 ``/api/arbiter/status`` 的 lane 段 schema（settings_
        routes 消费方，键集只增不减——读侧按键取值，新增键向后兼容）。
        锁内组装保证各计数同帧一致；此前该端点跨模块直读 _queue/_active
        等私有结构（code-review 21372fd6d003），现由数据属主统一封装，
        车道内部结构变更不再静默破坏读侧端点。
        """
        with self._lock:
            return {
                "enabled": self.enabled,
                "queue_depth": self._queue.qsize(),
                "active_signatures": sorted(self._active),
                "failure_counts": dict(self._failure_counts),
                "dispositioned_total": len(self._dispositioned),
                "deadmanned_total": len(self._deadmanned),
                # 探针拦截累计（d488eb0ddbeb）：与在飞 dedup 在返回字上同
                # 形态，单列供运维读出「派发被车道环境不可用拦住」
                "preflight_blocked_total": self._preflight_blocked_total,
            }

    def _pending_machine_alerts(self) -> Dict[str, dict]:
        """pending（未处理）机器升级告警索引：spec → 最新一条。

        机器升级告警 = kind=escalation ∧ 未 handled ∧ signal_type 在触发面
        （触发面黑名单制：in_trigger_surface 只读 chain.blacklist 配置，
        非黑名单即入——「冻结+告警」成对语义的告警半边；原
        ARBITER_TRIGGER_SIGNAL_TYPES 白名单机制已退役，词表仅存词汇
        机械枚举基线用途）。
        freeze_spec 人工冻结不产告警对——无索引命中即天然排除（回扫判据
        反查侧）。read_all 最新在前，首个命中即该 spec 最新 pending 告警
        （同 spec 多条历史告警只取最新，回扫描述以最新现场为准）。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION

            records = AdminStore(self.project_root, self.logger).read_all()
        except Exception as e:
            self._log("warning", f"arbiter 回扫告警索引读取失败（按空集降级）: {e}")
            return {}
        out: Dict[str, dict] = {}
        for rec in records:
            if not isinstance(rec, dict) or rec.get("kind") != ESCALATION:
                continue
            if rec.get("handled"):
                continue
            signal_type = str(rec.get("signal_type") or "")
            if not self.in_trigger_surface(signal_type):
                continue
            spec = str(rec.get("spec") or "")
            if spec and spec not in out:
                out[spec] = rec
        return out

    def _ledger_sigs(self, kinds: set) -> set:
        """台账签名集（跨重启 dedup 单实现）：只取 kind 命中 kinds 集合者。

        kinds 必传。现行唯一口径 = dead-man 永久例外（事件触发面与回扫
        共用：台账 kind=dead-man 才代表该签名已停机过、不得再次自主
        处置）。add-escalation-chain-admin-arbiter 3.3 配额制反转后回扫
        不再按台账全量排除（原 kinds=None 全量口径已无消费方、分支删除，
        查询任意 kind 集合仍可用本方法直传）。
        load_arbiter_ledger 自带 fail-open（IO 失败/坏行按空集降级），
        读失败按无台账处理照旧放行。
        读缓存（code-review fd762a606443）：台账 append-only 无轮转，
        全量 read_text+逐行 json.loads 成本随台账线性增长，且本方法在
        submit_trigger 关键路径（每次触发）与每轮回扫上——按
        （mtime_ns, size）双键失效缓存解析投影（不持有全量记录 dict）：
        台账新写任一键变化即整体失效重读，未变时零读盘复用。stat 失败
        （文件不存在）不缓存、每次直读（读侧 fail-open 空集，台账创建后
        自然进入缓存轨道）。缓存读写均为原子引用赋值，并发 miss 的重复
        读盘幂等（后写覆盖同值），不加锁。
        """
        path = arbiter_ledger_path(self.project_root)
        try:
            st = path.stat()
            cache_key = (st.st_mtime_ns, st.st_size)
        except OSError:
            cache_key = None
        if (
            cache_key is not None
            and self._ledger_cache_key == cache_key
            and self._ledger_sig_pairs is not None
        ):
            pairs = self._ledger_sig_pairs
        else:
            records = load_arbiter_ledger(self.project_root)
            pairs = [
                (str(rec.get("signature") or ""), rec.get("kind"))
                for rec in records
            ]
            if cache_key is not None:
                self._ledger_cache_key = cache_key
                self._ledger_sig_pairs = pairs
        return {sig for sig, kind in pairs if kind in kinds}

    def _backlog_candidates(self, sm) -> List[dict]:
        """存量回扫候选判定：frozen=true ∧ 同 spec pending 机器升级告警。

        - ``frozen_until`` 非空（定时冻结）显式排除（scheduled-unfreeze 自愈
          在先，与事件触发面同口径）；
        - 无成对 pending 告警的 frozen 条目（人工冻结形态）排除；
        - 签名已在处置台账（任意 kind——disposition/escalation/failed/
          dead-man/recurrence 都代表 Arbiter 已调查过该签名）排除：跨重启
          幂等兜底（进程内存 dedup 集合随重启清空，台账是既有持久层，
          不另记回扫簿）；
        - spec 名路径不安全（内插 run_id/路径前科防御）排除。
        """
        from core.pm_engine.verification.serving import _spec_name_path_error

        try:
            specs = sm.read_all() or {}
        except Exception as e:
            self._log("warning", f"arbiter 回扫 STATE 读取失败（按空集降级）: {e}")
            return {}
        alert_index = self._pending_machine_alerts()
        # 回扫排除配额制（add-escalation-chain-admin-arbiter 3.3）：旧「签名在
        # 台账（任意 kind）即排除」的单次纪律改为配额制——只排除（a）dead-man
        # 永久例外（台账 kind=dead-man，跨重启单次，例外不复位）与（b）复现
        # 配额已耗尽的签名（拍板计数 chain 状态文件持久化，跨重启有效）。
        # 配额未耗尽的签名重启后重新可扫（冻结核据仍在、信号未闭环——配额
        # 剩余次数内重试是配额制的本义）；进程内 dedup 由 submit_trigger 的
        # _active/dedup 兜底，不会同轮重复派发。
        deadman_ledger = self._ledger_sigs(kinds={"dead-man"})
        quota = self._chain_quota()
        rulings_cap = self._arbiter_rulings_quota()
        out: List[dict] = []
        for name, entry in specs.items():
            # per-candidate 容错（code-review 659188b1f8cc）：单候选判定
            # 失败不中断整轮扫描（对齐 sweep_backlog「单个候选失败不中断
            # 整轮」承诺）——留 warning 继续，不让一处异常使整轮回扫作废。
            try:
                e = entry or {}
                if not e.get("frozen"):
                    continue
                if str(e.get("frozen_until") or "").strip():
                    continue
                spec = str(name)
                alert = alert_index.get(spec)
                if alert is not None:
                    signal_type = str(alert.get("signal_type") or "")
                    severity = str(alert.get("severity") or "major")
                    description = str(alert.get("description") or "")
                    evidence = str(alert.get("evidence") or "")
                    recommended_action = str(alert.get("recommended_action") or "")
                    alert_id = str(alert.get("id") or "")
                else:
                    # 机器证据第二/三半边（2026-11-01）：告警半边随生命周期衰减
                    # （escalation 会被自愈收口置 handled），frozen 却无限期持续
                    # ——陈旧欠账必须靠不衰减的持久证据回扫。持久半边=咽喉标记
                    # （freeze_for_human 写 _frozen_source/_frozen_signal_type）
                    # 与遗留机器冻结菜单文案（标记上线前的存量标本，evo-refine
                    # 候选=0 二段根因实证）。
                    frozen_signal = str(e.get("_frozen_signal_type") or "")
                    has_marker = (
                        str(e.get("_frozen_source") or "") == "machine"
                        and bool(frozen_signal)
                    )
                    has_legacy_menu = (
                        ARBITER_LEGACY_MACHINE_FREEZE_MENU
                        in str(e.get("error") or "")
                    )
                    if not has_marker and not has_legacy_menu:
                        continue
                    signal_type = frozen_signal or "verify_env_blocked"
                    severity = "major"
                    description = str(e.get("error") or "")[:200]
                    evidence = ""
                    recommended_action = ""
                    alert_id = ""
                sig = arbiter_failure_signature(spec, signal_type)
                if sig in deadman_ledger or sig in self._deadmanned:
                    continue
                if self._safe_rulings(quota, sig) >= rulings_cap:
                    continue
                if _spec_name_path_error(spec):
                    self._log(
                        "warning",
                        f"arbiter 回扫跳过路径不安全 spec={spec!r}",
                    )
                    continue
                out.append(
                    {
                        "spec": spec,
                        "signal_type": signal_type,
                        "signature": sig,
                        "severity": severity,
                        "description": description,
                        "evidence": evidence,
                        "recommended_action": recommended_action,
                        "alert_id": alert_id,
                    }
                )
            except Exception as exc:
                self._log(
                    "warning",
                    f"arbiter 回扫候选判定失败（跳过该候选继续）: spec={name} {exc}",
                )
                continue
        return out

    def sweep_backlog(self, *, source: str = "backlog-sweep") -> dict:
        """执行一次存量回扫：命中者经既有 dedup/单飞/预算管线入队派发。

        判据见 :meth:`_backlog_candidates`。派发复用 :meth:`submit_trigger`
        （同签名 dedup / 单飞队列 / 预算随触发携带，不建第二套派发路径）；
        与事件触发竞写同签名时 submit_trigger 侧 dedup 兜底不重复派发。
        单个候选排队登记失败（队列满）不中断整轮回扫——其余候选继续，
        失败项显式记入返回摘要（不吞错报假成功）。
        """
        cfg = self.config()
        if not cfg.get("enabled"):
            self._log("info", f"arbiter 存量回扫跳过（enabled=false）source={source}")
            return {
                "status": "disabled",
                "source": source,
                "dispatched": [],
                "deduped": [],
                "preflight_blocked": [],
                "escalated": [],
                "skipped": [],
                "failed": [],
            }
        sm = self._resolve_state_machine()
        if sm is None:
            self._log("warning", "arbiter 存量回扫不可用（state_machine 未装配），跳过")
            return {
                "status": "unavailable",
                "source": source,
                "dispatched": [],
                "deduped": [],
                "preflight_blocked": [],
                "escalated": [],
                "skipped": [],
                "failed": [],
            }
        try:
            candidates = self._backlog_candidates(sm)
        except Exception as e:  # 扫描段故障不中断整轮（不吞：留 warning 痕）
            self._log("warning", f"arbiter 回扫候选扫描失败（按空集降级）: {e}")
            candidates = []
        dispatched: List[str] = []
        deduped: List[str] = []
        preflight_blocked: List[str] = []
        escalated: List[str] = []
        skipped: List[dict] = []
        failed: List[dict] = []
        for cand in candidates:
            sig = str(cand.get("signature") or "")
            try:
                outcome = self.submit_trigger(
                    spec=str(cand.get("spec") or "global"),
                    signal_type=str(cand.get("signal_type") or ""),
                    severity=str(cand.get("severity") or "major"),
                    description=str(cand.get("description") or ""),
                    evidence=str(cand.get("evidence") or ""),
                    recommended_action=str(cand.get("recommended_action") or ""),
                    alert_id=str(cand.get("alert_id") or "") or None,
                    source=source,
                )
            except RuntimeError as e:
                failed.append({"signature": sig, "error": str(e)[:300]})
                continue
            except Exception as e:  # 单候选故障不中断整轮（不吞：记摘要）
                failed.append({"signature": sig, "error": f"回扫派发异常: {e}"[:300]})
                continue
            if outcome == "queued":
                dispatched.append(sig)
                # 探针已复位（派发成功）：清陈旧拦截标记，防后续误标真 dedup
                with self._lock:
                    self._preflight_blocked_sigs.discard(sig)
            elif outcome == "deduped" and sig in self._preflight_blocked_sigs:
                # 探针拦截形态单列（d488eb0ddbeb）：submit_trigger 零新契约
                # 仍返回 deduped，靠拦截签名集分辨「车道环境不可用未派发」
                # 与「同签名在飞折叠」——防环境长期不可用时 deduped 虚高、
                # dispatched=0 而摘要读不出「整轮被探针拦截」。消费即清。
                with self._lock:
                    self._preflight_blocked_sigs.discard(sig)
                preflight_blocked.append(sig)
            elif outcome == "deduped":
                deduped.append(sig)
            elif outcome == "recurrence-escalated":
                # 配额耗尽/dead-man 例外直升级：TOCTOU 窗口（扫描时配额未
                # 满、提交时已被并发拍板耗尽）下属合法终态，单列与
                # dispatched/deduped/failed 并列（50fa892f29ae——不混入
                # 供异常审计的 skipped）
                escalated.append(sig)
            else:
                # disabled/excluded：黑名单制触发面下回扫候选默认在面内，
                # 此二形态仅在候选扫描与提交之间配置热更新（enabled 翻转/
                # 黑名单变更）的窄窗内合法出现，显式记录供审计（不静默丢弃）
                skipped.append({"signature": sig, "outcome": outcome})
        summary = {
            "status": "ok",
            "source": source,
            "scanned": len(candidates),
            "dispatched": dispatched,
            "deduped": deduped,
            "preflight_blocked": preflight_blocked,
            "escalated": escalated,
            "skipped": skipped,
            "failed": failed,
        }
        self._log(
            "info",
            f"arbiter 存量回扫完成 source={source} 候选={len(candidates)} "
            f"派发={len(dispatched)} dedup={len(deduped)} "
            f"探针拦截={len(preflight_blocked)} 升级={len(escalated)} "
            f"失败={len(failed)} 跳过={len(skipped)}"
            + (f" {[(s['signature'], s['outcome']) for s in skipped]}"
               if skipped else ""),
        )
        return summary

    def _bind_alert(self, sig: str, alert_id: str):
        """把后落地的 alert_id 绑到已在飞/排队的同签名触发上。

        freeze_for_human 咽喉先入队（此刻 alert 尚未落盘）、告警写盘后
        _send_human_escalation_alert 咽喉再报同签名——本方法把 alert_id 补绑
        到触发上，处置成功/升级才有原位挂靠目标。绑定时签名在 set 中找不到
        对应 trigger（并发窗口）则静默跳过（dedup 语义不变）。
        """
        with self._lock:
            # queue 无检索原语：以快照重建方式补绑（队列深度上限 8，重建廉价）
            drained: List[dict] = []
            while True:
                try:
                    drained.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            bound = False
            for trig in drained:
                if not bound and trig.get("signature") == sig:
                    trig["alert_id"] = alert_id
                    bound = True
                try:
                    self._queue.put_nowait(trig)
                except queue.Full:  # pragma: no cover - 深度上限内自洽
                    self._log("error", f"arbiter 补绑回队失败（队列满）: sig={sig}")
            if bound:
                return
        # 队列中没有（可能已出队在飞）：登记到待绑表，worker 取到触发后合并
        # ——简化：在飞触发由 worker 消费时从 _pending_alert_binds 取补绑。
        with self._lock:
            self._pending_binds.setdefault(sig, alert_id)

    def _consume_pending_bind(self, sig: str, trigger: dict):
        """处置终点回捞迟到补绑（调用方须已持 ``self._lock``）。

        _worker_loop 只在出队瞬间消费一次 _pending_binds；空闲 worker 微秒级
        出队后告警才落盘（freeze 咽喉先于 alert 咽喉数秒），迟到的 alert_id
        若不在处理终点回捞，处置成功/升级/死人开关永远拿不到原位挂靠目标
        （原告警滞留 pending 不终态化），且滞留条目会在同签名失败重试时被
        误绑到新触发上。锁内 pop 后合并，剩余滞留清零。
        """
        bind = self._pending_binds.pop(sig, None)
        if bind and not trigger.get("alert_id"):
            trigger["alert_id"] = bind

    # ── worker（全局单飞串行消费）────────────────────────────────────

    def _ensure_worker(self):
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="arbiter-lane-worker",
            )
            self._worker.start()

    def _worker_loop(self):
        while True:
            try:
                trigger = self._queue.get()
            except Exception:  # pragma: no cover - 队列关闭等病态
                continue
            sig = ""
            try:
                sig = str(trigger.get("signature") or "")
                with self._lock:
                    bind = self._pending_binds.pop(sig, None)
                    if bind and not trigger.get("alert_id"):
                        trigger["alert_id"] = bind
                self._process_trigger(trigger)
            except Exception as e:
                # 单个触发的处理崩溃不得杀死 worker（静默死亡反例：至少落
                # 日志）；同时清掉 _active 占位（code-review 4e7ec307f1d8）
                # ——异常若落在三出口清位之前（如 report 形态异常在分类判定
                # 处抛出），占位滞留会使同签名后续触发在 submit_trigger 恒判
                # deduped（只绑 alert 不派发、不落台账、不升级），升级边零
                # 留痕失明直至进程重启，与「MUST NOT 静默死亡」设计承诺相悖。
                # discard 不存在的元素为无害 no-op（三出口已清位时）。
                with self._lock:
                    self._active.discard(sig)
                self._log(
                    "error",
                    f"arbiter 触发处理异常（继续下一触发）: sig={sig} {e}",
                )
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    # ── 主流程（4.1）：消费 → 调查 run → 分类 → 处置/升级 ─────────────

    def _process_trigger(self, trigger: dict):
        spec = str(trigger.get("spec") or "global")
        try:
            result = self._run_investigation(trigger)
        except Exception as e:
            result = {"ok": False, "error": f"arbiter run 派发异常: {e}", "report": {}}
        # 调查产物形态防御（code-review 5a89503a3152，与 _pending_machine_
        # alerts 的记录形态防御同口径）：result/report 非dict 时按空值降级
        # ——防 .get 抛 AttributeError 越过三出口分类直落 worker 兜底
        if not isinstance(result, dict):
            result = {}
        report = result.get("report")
        if not isinstance(report, dict):
            report = {}
        budget = result.get("budget") or {}
        if not result.get("ok"):
            self._on_run_failed(trigger, result, budget)
            return
        outcome = str(report.get("outcome") or "").strip().lower()
        if outcome == "resolved":
            self._on_disposition_success(trigger, result, budget)
        elif outcome == "escalate":
            self._on_escalate(
                trigger,
                result,
                budget,
                reason=str(report.get("escalation_reason") or "arbiter 判定须人类拍板"),
            )
        else:
            # 产物硬门外的语义失败（outcome 非法/缺失）按失败计（死人开关）
            self._on_run_failed(
                trigger,
                {
                    "ok": False,
                    "error": f"arbiter 报告 outcome 非法: {outcome!r}",
                    "report": report,
                },
                budget,
            )

    # ── 链同步接单（add-escalation-chain-admin-arbiter 3.1/3.4）────────

    def process_chain_handoff(self, trigger: dict) -> str:
        """处置链第二级同步接单：一次调查 run 的同步驱动与分类。

        与异步队列路径（submit_trigger → worker → _process_trigger）共用同
        一套调查机器（_run_investigation + 结果分类三出口），差异仅在驱动
        形态：链 worker 串行直调本方法并按返回值推进链序——
        ``"resolved"``=链闭环（拍板成功、side-effects 已落）；
        ``"escalated"``=Arbiter 自判须人类拍板，链终点上升；
        ``"dead-man"``=死人开关触发（半成品包已升级），链终点上升；
        ``"failed"``=未达阈值，链内循环重派（重派上限由链侧 bounded by
        max_consecutive_failures，车道内部连败计数自然收敛到 dead-man）；
        ``"infra-failed"``=基础设施故障或派发前置探针拦截（不进死人开关、
        不升级人工）——链侧专用消费分支承接：不循环重派、不上升链终点，
        deferred 让行范式留痕等探针复位/下次触发面回喂
        （harden-arbiter-lane-resilience 2.1/3.2）。

        触发 dict 约定（链传入）：标准字段（signature/spec/signal_type/
        severity/description/evidence/recommended_action）＋转单载荷
        （admin_trail=Admin 尝试痕、admin_handoff_reason，经 prompt_builder
        {chain_trail} 注入调查 prompt，task 3.1）＋收集器
        （_chain_ledger_ids 列表，_write_ledger 回填台账条目 id 供链终点
        上升件携带台账回链）。_chain_unfrozen/_chain_endpoint_kind/
        _chain_endpoint_reason/_chain_run_id 由本方法与三出口回填、链读侧
        消费。不经单飞队列（链 worker 自身串行），不写 _active（链在飞
        记账归链状态文件 in_flight 区管）。
        """
        sig = str(trigger.get("signature") or "")
        # ── 派发前置探针拦截（agent-lane-preflight R3）────────────────
        # 拦截点位于 _consume_pending_bind 之前；命中零状态变更（不写
        # _active、不消费补绑、不落台账、不计配额），链侧按 infra-failed
        # 消费分支让行留痕（零状态变更含链在办区——mark/clear 均在调用方
        # _process_item，本方法返回即让链正常 clear，无滞留）。失败原因
        # 回填 trigger 工作字段供链事件留痕可读（trigger 是链本次调用专属
        # dict，非持久状态）。
        if not self._preflight_gate():
            with self._lock:
                self._preflight_blocked_total += 1
            trigger["_chain_failure_reason"] = (
                "派发前置自检拦截：车道环境不可用（探针 unhealthy）"
            )
            return "infra-failed"
        with self._lock:
            self._consume_pending_bind(sig, trigger)
        try:
            result = self._run_investigation(trigger)
        except Exception as e:
            result = {"ok": False, "error": f"arbiter run 派发异常: {e}", "report": {}}
        # 调查产物形态防御（同 _process_trigger，code-review 5a89503a3152）
        if not isinstance(result, dict):
            result = {}
        trigger["_chain_run_id"] = str(result.get("run_id") or "")
        report = result.get("report")
        if not isinstance(report, dict):
            report = {}
        budget = result.get("budget") or {}
        if not result.get("ok"):
            return self._on_run_failed(trigger, result, budget)
        outcome = str(report.get("outcome") or "").strip().lower()
        if outcome == "resolved":
            self._on_disposition_success(trigger, result, budget)
            return "resolved"
        if outcome == "escalate":
            self._on_escalate(
                trigger,
                result,
                budget,
                reason=str(report.get("escalation_reason") or "arbiter 判定须人类拍板"),
            )
            return "escalated"
        # 产物硬门外的语义失败（outcome 非法/缺失）按失败计（死人开关）
        return self._on_run_failed(
            trigger,
            {
                "ok": False,
                "error": f"arbiter 报告 outcome 非法: {outcome!r}",
                "report": report,
            },
            budget,
        )

    def _run_investigation(self, trigger: dict) -> dict:
        """启动一次 dsh 车道调查 run（run_arbiter；预算记账贯穿 run 生命周期）。

        预算记账（验收「预算记账贯穿」）：墙钟由 _effective_run_timeout 对
        arbiter 取 min 封顶（2.1），token 事后记账（usage_info 四键累计）；
        两维耗尽位进 budget dict 供死人开关判定。
        """
        from core.agent_runner import maintenance_runs

        runner = self._resolve_runner()
        if runner is None:
            return {"ok": False, "error": "agent_runner 不可用（车道未装配）", "report": {}}
        result = maintenance_runs.run_arbiter(runner, trigger)
        usage = result.get("usage_info") or {}
        tokens_used = sum(
            int(usage.get(k) or 0)
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        )
        cfg = self.config()
        token_budget = int(cfg.get("budget_tokens") or ARBITER_BUDGET_TOKENS_DEFAULT)
        wall_budget = float(
            cfg.get("budget_wallclock_s") or ARBITER_BUDGET_WALLCLOCK_S_DEFAULT
        )
        elapsed = float(result.get("elapsed_s") or 0.0)
        result["budget"] = {
            "started_at": trigger.get("enqueued_at"),
            "finished_at": _utcnow_iso(),
            "wallclock_budget_s": wall_budget,
            "elapsed_s": elapsed,
            "wallclock_exhausted": bool(wall_budget > 0 and elapsed > wall_budget),
            "tokens_used": tokens_used,
            "token_budget": token_budget,
            "tokens_exhausted": bool(token_budget > 0 and tokens_used > token_budget),
        }
        return result

    def _resolve_runner(self):
        """取 AgentRunner 门面（PMEngine 装配时注入；测试可直设）。"""
        runner = getattr(self, "_runner_ref", None)
        return runner

    def set_runner(self, runner):
        self._runner_ref = runner

    # ── 结果分类三出口 ────────────────────────────────────────────────

    def _on_disposition_success(self, trigger: dict, result: dict, budget: dict):
        """处置成功：框架侧直执行收尾 + 告警零噪音终态化 + 台账五段 + 配额记账。"""
        sig = str(trigger.get("signature") or "")
        with self._lock:
            self._failure_counts.pop(sig, None)
            self._active.discard(sig)
            self._dispositioned.add(sig)
            self._consume_pending_bind(sig, trigger)
        # 复现配额记账（add-escalation-chain-admin-arbiter 3.3）：拍板一次计
        # 一次（持久化 chain 状态文件；配额耗尽后同签名复发由 submit_trigger
        # 判定强制上升）。进程内 _dispositioned 集合保留仅供 snapshot() 水位
        # 展示，不再参与派发判定。
        quota = self._chain_quota()
        if quota is not None:
            try:
                quota.count_arbiter_ruling(sig)
            except Exception as e:
                self._log("warning", f"拍板配额计数失败（fail-open）: sig={sig} {e}")
        report = result.get("report") or {}
        side = self._apply_disposition_side_effects(trigger, report)
        # 链注记（escalation_chain._run_arbiter_phase 消费）：解冻结果回写
        # 触发 dict，链据此判断闭环 side-effects 是否已含解冻。
        if side.get("unfrozen"):
            trigger["_chain_unfrozen"] = True
        alert_id = trigger.get("alert_id")
        evidence_ref = "; ".join(str(x) for x in (report.get("evidence_refs") or []))
        action_text = self._render_actions(report)
        if side.get("unfrozen"):
            action_text += f"；解冻→显式 status={side.get('unfreeze_status')}"
        elif side.get("unfreeze_error"):
            action_text += f"；解冻未执行（{side['unfreeze_error']}）"
        if side.get("cleaned_paths"):
            action_text += f"；清理无主产物 {len(side['cleaned_paths'])} 项"
        if side.get("budget_override") is not None:
            action_text += f"；预算 override→{side['budget_override']}"
        entry = self._write_ledger(
            trigger,
            result,
            kind="disposition",
            report=report,
            budget=budget,
            action_or_upgrade=action_text,
            status_after=str(report.get("status_after") or side.get("unfreeze_status") or ""),
        )
        resolved = False
        if alert_id:
            resolved = self._finalize_alert(
                alert_id,
                summary=str(report.get("summary") or ""),
                evidence_ref=evidence_ref or str(entry.get("id") or ""),
                run_id=str(result.get("run_id") or ""),
            )
        self._log(
            "info",
            f"arbiter 自主处置完成 spec={trigger.get('spec')} sig={sig} "
            f"alert_finalized={resolved} ledger={entry.get('id')} side={side}",
        )
        # 框架缺口路由（gap→todo；禁立项红线，add-arbiter-gap-todo-routing）
        # 触发 run_id 回填（与 process_chain_handoff 回填 _chain_run_id 对齐）：
        # trigger 本身无 run_id 写点（run_arbiter 只写 prompt_detail 拷贝），
        # 不回填则 gap 条目证据段「触发 run_id=未知」、gap-noted 台账 run_id
        # 恒为空串，缺口发现无法回溯到产出它的调查 run。
        trigger["run_id"] = str(result.get("run_id") or trigger.get("run_id") or "")
        self._apply_gaps(trigger, report)

    def _apply_disposition_side_effects(self, trigger: dict, report: dict) -> dict:
        """处置动作框架侧直执行（4.1 ①③类收尾；解冻含验证计数清零语义）。

        - 解冻：报告 status_after 是合法 SpecStatus 且 spec 当前 frozen 时执行
          ``unfreeze_spec(spec, status=<显式值>)``——绝不依赖 parse_orig_status
          ready 兜底（spec「显式 status 解冻」硬约束）；报告缺显式 status 时
          解冻不执行、留冻结待人工（宁可不动状态也不拍脑袋解冻）。
          unfreeze_spec 自带「重启重验计数一并清零」（fix-daemon-lifecycle-races
          D3）——③验证计数清零由该调用一并完成，不另设清零写点。
        - 清理（②删除无主坏产物）：报告 cleanup_paths 经 ``_safe_cleanup_path``
          白名单过滤后删除（越界/敏感路径一律拒绝）。
        - 预算 override（add-escalation-chain-admin-arbiter 3.2 预算豁免拍板
          动作面）：报告 budget_override 非空时写入 spec 预算覆盖字段（复用
          ``impl_run_budget_override`` 既有字段，不新增 schema；夹紧口径与
          闸门/Dashboard 同源 clamp_impl_run_budget）。非法值/写失败只留
          WARNING 不阻断解冻主流程。
        """
        spec = str(trigger.get("spec") or "")
        side: Dict[str, Any] = {"unfrozen": False, "cleaned_paths": []}
        status_after = str(report.get("status_after") or "").strip()
        sm = self._resolve_state_machine()
        if sm is not None and spec and spec != "global":
            try:
                from core.state_machine import SpecStatus

                entry = (sm.read_all() or {}).get(spec) or {}
                # 冻结判定（fix-restart-dual-dispatch S4 结构化字段口径）：
                # frozen=True 字段而非 "frozen" 状态值——机器冻结落
                # status=blocked + frozen=True（freeze_for_human 单一入口）
                if entry.get("frozen"):
                    if status_after and status_after in SpecStatus.ALL:
                        side["unfrozen"] = bool(
                            sm.unfreeze_spec(spec, status=status_after)
                        )
                        side["unfreeze_status"] = (
                            status_after if side["unfrozen"] else None
                        )
                    else:
                        side["unfreeze_error"] = (
                            "报告未给合法显式 status（拒绝 parse 兜底，留冻结待人工）"
                        )
            except Exception as e:
                side["unfreeze_error"] = f"解冻执行异常: {e}"
                self._log("error", f"arbiter 解冻执行异常 spec={spec}: {e}")
            # 预算豁免拍板动作面（3.2）：budget_override 拍板值落 per-spec
            # 预算覆盖（既有字段，无则写、有则更新——拍板即最新意志）
            override_raw = report.get("budget_override")
            if override_raw is not None and str(override_raw).strip() != "":
                try:
                    from core.pm_engine.budget import apply_budget_override

                    applied = apply_budget_override(sm, spec, override_raw)
                    if applied is not None:
                        side["budget_override"] = applied
                    else:
                        self._log(
                            "warning",
                            f"arbiter 预算 override 非法未落盘 spec={spec}: "
                            f"{override_raw!r}",
                        )
                except Exception as e:
                    self._log(
                        "warning",
                        f"arbiter 预算 override 写入失败（不阻断解冻）spec={spec}: {e}",
                    )
        for raw in (report.get("cleanup_paths") or []):
            path = self._safe_cleanup_path(raw)
            if path is None:
                continue
            try:
                if path.is_dir():
                    import shutil

                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
                side["cleaned_paths"].append(str(path))
            except OSError as e:
                self._log("warning", f"arbiter 无主产物清理失败 path={path}: {e}")
        return side

    def _safe_cleanup_path(self, raw) -> Optional[Path]:
        """cleanup_paths 白名单过滤（②类动作的有界执行边界）。

        只放行两类「无主坏产物」位置：``.claude/worktrees/<name>``（孤儿
        worktree）与 ``.fenix/tmp/**``；其余一律拒绝（防报告注入把清理变成
        任意删——spec「白名单外只产裁决包不擅动」的框架侧镜像）。
        """
        try:
            root = self.project_root.resolve()
            path = Path(str(raw or "")).expanduser()
            if not path.is_absolute():
                path = root / path
            path = path.resolve()
        except (OSError, ValueError):
            return None
        if path == root or root not in path.parents:
            return None
        try:
            rel = path.relative_to(root)
        except ValueError:
            return None
        parts = rel.parts
        # 白名单只放行根目录之下的具体子路径（len >= 3）：与
        # .claude/worktrees、.fenix/tmp 完全相等的根目录本身不算「无主坏
        # 产物位置」，两级前缀放行即等于整树删除（code-review item
        # e38465a2a91e）。
        if len(parts) >= 3 and parts[0] == ".claude" and parts[1] == "worktrees":
            return path
        if len(parts) >= 3 and parts[0] == ".fenix" and parts[1] == "tmp":
            return path
        return None

    def _on_escalate(self, trigger: dict, result: dict, budget: dict, reason: str):
        """升级：裁决包同 alert_id 原位静默更新 + 推 pending + 台账。"""
        sig = str(trigger.get("signature") or "")
        with self._lock:
            self._active.discard(sig)
            self._consume_pending_bind(sig, trigger)
        # 升级裁决同样计拍板配额（add-escalation-chain-admin-arbiter 3.3）：
        # 拍板=一次完整调查的裁决（resolved/escalate 皆算）——升级终态签名
        # 若不计数，重启回扫会在配额外无限重派升级件（人工噪音放大器）。
        # 计数失败 fail-open（与 _on_disposition_success 同口径）。
        quota = self._chain_quota()
        if quota is not None:
            try:
                quota.count_arbiter_ruling(sig)
            except Exception as e:
                self._log("warning", f"升级拍板配额计数失败（fail-open）: sig={sig} {e}")
        # 链注记（escalation_chain._run_arbiter_phase 消费）：Arbiter 自判
        # 须人类拍板（escalate）——链终点以裁决包理由上升。
        trigger["_chain_endpoint_kind"] = "arbiter-escalated"
        trigger["_chain_endpoint_reason"] = str(reason or "")[:400]
        report = result.get("report") or {}
        self._write_ledger(
            trigger,
            result,
            kind="escalation",
            report=report,
            budget=budget,
            action_or_upgrade=reason,
            status_after="",
        )
        alert_id = trigger.get("alert_id")
        if alert_id:
            self._upgrade_alert(
                alert_id,
                report=report,
                recommended=str(
                    report.get("recommended_action")
                    or trigger.get("recommended_action")
                    or ""
                ),
                run_id=str(result.get("run_id") or ""),
                reason=reason,
            )
        self._log(
            "warning",
            f"arbiter 产裁决包升级 spec={trigger.get('spec')} sig={sig} reason={reason[:120]}",
        )
        # 框架缺口路由（gap→todo；禁立项红线，add-arbiter-gap-todo-routing）
        # 触发 run_id 回填（同 _on_disposition_success：trigger 无 run_id 写点）
        trigger["run_id"] = str(result.get("run_id") or trigger.get("run_id") or "")
        self._apply_gaps(trigger, report)

    def _on_run_failed(self, trigger: dict, result: dict, budget: dict) -> str:
        """失败路径：infra/judgment 分级 → 各自通道。

        分级（harden-arbiter-lane-resilience 2.1）：预算耗尽恒判 judgment
        （真实车道真实消耗）；其余按 :func:`classify_lane_failure`——
        0 rounds（无 API 往返样本，信封 rounds 透传真值）或环境指纹命中
        （MISSING_CREDENTIAL / No such file or directory / skipping profile
        bundle）判 infra。

        返回终态字（add-escalation-chain-admin-arbiter 3.4 失败双轨的链消费
        口径 + harden 2.1 infra 终态）：
        ``"dead-man"``（死人开关触发，半成品包已升级）、``"failed"``
        （judgment 未达阈值，等待同签名下次触发重试）、``"infra-failed"``
        （基础设施故障——**不进死人开关、不升级人工**，台账 kind=
        infra-failed 计独立计数，健康探针复位后同签名恢复自主处置资格）。
        链同步驱动按返回值决定循环重派或终点上升（infra-failed 由链侧
        专用消费分支承接：不重派不上升，deferred 范式留痕等回喂）。
        """
        sig = str(trigger.get("signature") or "")
        cfg = self.config()
        max_fail = int(
            cfg.get("max_consecutive_failures")
            or ARBITER_MAX_CONSECUTIVE_FAILURES_DEFAULT
        )
        max_infra = int(
            cfg.get("max_consecutive_infra_failures")
            or ARBITER_MAX_CONSECUTIVE_INFRA_FAILURES_DEFAULT
        )
        reason = str(result.get("error") or "run 失败")
        half_report = {
            "summary": str((result.get("report") or {}).get("summary") or ""),
            "evidence_refs": (result.get("report") or {}).get("evidence_refs") or [],
        }
        trigger["_chain_failure_reason"] = reason[:400]
        # ── infra/judgment 分级（预算耗尽恒判 judgment，先行短路）──────
        if budget.get("tokens_exhausted") or budget.get("wallclock_exhausted"):
            failure_class = "judgment"
        else:
            try:
                from core.agent_runner.lane_preflight import classify_lane_failure

                failure_class = classify_lane_failure(result)
            except Exception as e:
                # 分级器不可用按现行 judgment 语义（保守——不因新机制故障
                # 改变既有死人开关行为）
                self._log(
                    "warning",
                    f"失败分级器不可用（按 judgment 语义处理）: {type(e).__name__}: {e}",
                )
                failure_class = "judgment"
        if failure_class == "infra":
            return self._on_infra_failed(
                trigger, result, budget, sig, reason, half_report, max_infra
            )
        with self._lock:
            count = self._failure_counts.get(sig, 0) + 1
            self._failure_counts[sig] = count
            self._active.discard(sig)
            self._consume_pending_bind(sig, trigger)
        if count >= max_fail or budget.get("tokens_exhausted") or budget.get(
            "wallclock_exhausted"
        ):
            with self._lock:
                self._deadmanned.add(sig)
            trigger["_chain_endpoint_kind"] = "arbiter-dead-man"
            trigger["_chain_endpoint_reason"] = (
                f"死人开关触发（连败 {count}/{max_fail} 或预算耗尽）: {reason[:300]}"
            )
            switch = (
                f"连败 {count}/{max_fail}"
                if count >= max_fail
                else "预算耗尽"
            )
            self._write_ledger(
                trigger,
                result,
                kind="dead-man",
                report={
                    "summary": half_report["summary"],
                    "evidence_refs": half_report["evidence_refs"],
                },
                budget=budget,
                action_or_upgrade=f"死人开关触发（{switch}）：停止自主尝试，半成品调查包升级人类。失败原因: {reason}",
                status_after="",
            )
            alert_id = trigger.get("alert_id")
            if alert_id:
                self._upgrade_alert(
                    alert_id,
                    report={
                        "summary": half_report["summary"]
                        or f"Arbiter run 未产出完整调查报告（{switch}）",
                        "evidence_refs": half_report["evidence_refs"],
                    },
                    recommended=str(trigger.get("recommended_action") or ""),
                    run_id=str(result.get("run_id") or ""),
                    reason=f"死人开关（{switch}）: {reason}",
                )
            self._log(
                "error",
                f"arbiter 死人开关触发 spec={trigger.get('spec')} sig={sig} "
                f"({switch})，半成品包升级 alert={alert_id}",
            )
            return "dead-man"
        else:
            self._write_ledger(
                trigger,
                result,
                kind="failed",
                report=half_report,
                budget=budget,
                action_or_upgrade=f"run 失败（{count}/{max_fail}），等待同签名下次触发重试: {reason}",
                status_after="",
            )
            self._log(
                "warning",
                f"arbiter run 失败 spec={trigger.get('spec')} sig={sig} "
                f"({count}/{max_fail}): {reason[:160]}",
            )
            return "failed"

    def _on_infra_failed(
        self,
        trigger: dict,
        result: dict,
        budget: dict,
        sig: str,
        reason: str,
        half_report: dict,
        max_infra: int,
    ) -> str:
        """infra 失败通道（harden-arbiter-lane-resilience 2.1，与 dead-man 通道并行互斥）。

        独立计数 ``_infra_failure_counts``（不烧 judgment 连败资格）；写台账
        kind=infra-failed（action 注明待健康探针复位）；**不**加
        ``_deadmanned``、**不**升级人工 alert——改 WARNING 日志 + 一次性
        「车道环境不可用」告警（dedup_key 单发，恢复经探针 healthy 自动
        关闭）。达上限同样只记台账+告警：资格保留，等探针复位（环境修复
        后签名恢复自主处置资格——2026-11-09 四签名秒挂 8h 事故的
        「环境恢复后资格无法恢复」缺口收口）。

        返回 ``"infra-failed"`` 终态字：异步路径（_process_trigger）忽略
        返回值零影响；链同步路径经 process_chain_handoff 透传，链侧
        infra-failed 消费分支承接（escalation_chain：不循环重派、不上升
        链终点、不升级人工，deferred 让行范式留痕）。
        """
        with self._lock:
            infra_count = self._infra_failure_counts.get(sig, 0) + 1
            self._infra_failure_counts[sig] = infra_count
            self._active.discard(sig)
            self._consume_pending_bind(sig, trigger)
        self._write_ledger(
            trigger,
            result,
            kind="infra-failed",
            report=half_report,
            budget=budget,
            action_or_upgrade=(
                f"基础设施故障（infra {infra_count}/{max_infra}）：车道环境"
                "不可用，不进死人开关、不升级人工——待健康探针复位后重试。"
                f"失败原因: {reason}"
            ),
            status_after="",
        )
        self._log(
            "warning",
            f"arbiter 基础设施故障分级（infra-failed，不进死人开关）"
            f"spec={trigger.get('spec')} sig={sig} "
            f"({infra_count}/{max_infra}): {reason[:160]}",
        )
        # 一次性「车道环境不可用」告警（dedup_key 单发；非人工升级——
        # 告警收口走探针 healthy 自动关闭，不走人工处置）
        try:
            from core.agent_runner.lane_preflight import ensure_lane_env_alert

            ensure_lane_env_alert(
                self.project_root,
                self.logger,
                reasons=[reason],
                origin="arbiter-run-infra-failed",
            )
        except Exception as e:
            self._log("warning", f"车道环境告警写入失败（fail-open）: {e}")
        return "infra-failed"

    # ── 前置自检与复位消费（agent-lane-preflight / harden 2.2）────────

    def _full_config(self) -> dict:
        """全量 config 读取（探针需要 agent.harness/agents.models/llm 段，
        非 arbiter 六键切片；失败回空 dict=探针按缺省选型 fail-open）。"""
        try:
            from core.config import ConfigLoader

            return ConfigLoader.resolve_config(self.project_root)
        except Exception as e:
            self._log("warning", f"探针用全量配置读取失败（按空配置降级）: {e}")
            return {}

    def _preflight_gate(self) -> bool:
        """派发前置探针闸（TTL 缓存内复用结论；返回 True=放行派发）。

        - unhealthy → False：调用方零状态变更返回既有终态字（异步
          deduped / 链 infra-failed），不消耗 infra 计数、不产半成品包；
        - healthy → True 放行，且此前有 infra 停机计数时触发复位
          （:meth:`on_lane_healthy`，能力一 R3「派发前置复位」触发点）。
        """
        ttl = int(
            self.config().get("preflight_ttl")
            or ARBITER_PREFLIGHT_TTL_DEFAULT
        )
        if self._preflight_cache.ttl_s != ttl:
            # TTL 热更新：重建缓存（下次取用按新 TTL 探测生效）
            self._preflight_cache = LanePreflightCache(ttl)
        health = self._preflight_cache.get_or_probe(
            self._full_config(), self.logger
        )
        if health.ok:
            self.on_lane_healthy(source="dispatch-preflight")
            return True
        self._log(
            "warning",
            "arbiter 派发前置自检拦截（车道环境不可用，零状态变更跳过本次"
            f"派发，信号靠触发面复报/回扫候选重扫回喂）: "
            + "；".join(health.reasons)[:400],
        )
        return False

    def on_lane_healthy(self, source: str = "preflight") -> None:
        """复位消费（harden-arbiter-lane-resilience 2.2 / R3）：健康信号
        → 清全部 infra 计数 + 日志留痕。

        judgment 连败计数（``_failure_counts``）与 dead-man 永久语义
        （``_deadmanned`` + 台账 dead-man 读侧）**不动**——那是对真实判断
        失败的资格治理，无复位（design §能力一复位消费）。infra 计数为空
        时静默返回（零写零日志，周期探针 healthy 高频复用不刷屏）。
        """
        with self._lock:
            had = bool(self._infra_failure_counts)
            self._infra_failure_counts.clear()
        if had:
            self._log(
                "info",
                f"车道健康，infra 计数复位（source={source}）——签名恢复"
                "自主处置资格（judgment 连败与 dead-man 不受影响）",
            )

    # ── 处置台账（4.2）───────────────────────────────────────────────

    def _write_ledger(
        self,
        trigger: dict,
        result: dict,
        *,
        kind: str,
        report: dict,
        budget: dict,
        action_or_upgrade: str,
        status_after: str,
    ) -> dict:
        """追加一条五段台账（现场快照/取证时间轴/根因/处置动作或升级理由/证据回链）。"""
        # 五段结构（LEDGER_SEGMENT_KEYS 同序）各段缺省补全（s7 台账完整验收）：
        # 失败/死人开关路径报告缺段时以真实失败现场/run 归档回链补位——落
        # 「无现场快照」式空占位等于缺段。
        failure_reason = str(result.get("error") or "")
        run_id_eff = result.get("run_id") or trigger.get("run_id")
        scene = str(report.get("scene_snapshot") or trigger.get("description") or "")
        if not scene.strip():
            scene = (
                f"run 失败现场（kind={kind}）: {failure_reason[:600]}"
                if failure_reason
                else f"触发现场（source={trigger.get('source')}，报告未带快照）"
            )
        root = str(report.get("root_cause") or "")
        if not root.strip():
            # 失败终点族（judgment 失败/死人开关/infra 分级）根因缺段以真实
            # 失败现场口径补位——infra-failed 同为失败终点（环境不可用），
            # 五段完整性验收不分 kind 豁免（test_arbiter_guardrails
            # TestLedgerCompleteness 全 kind 断言）。
            root = (
                "run 未产出根因（失败终点，成因见 action_or_upgrade 与失败现场）"
                if kind in ("failed", "dead-man", "infra-failed")
                else ""
            )
        evidence = list(report.get("evidence_refs") or [])
        if not evidence and run_id_eff:
            # 真实回链：run 归档转录（调查过程事实所在）
            evidence = [f".fenix/runs/{run_id_eff}.jsonl"]
        entry = {
            # 同毫秒并发写账撞 id 消歧（item 175d49d47a1b）：写点有多个并发
            # 线程（单飞 worker/submit_trigger 锁外复发/链 worker），毫秒粒度
            # 可撞车。随机尾段与 make_maintenance_run_id 的 x<rand> 先例同
            # 口径——id 仅作 _chain_ledger_ids 回链与按 id 反查的关联键，
            # 消费方不解析形态，追加尾段不破坏任何读侧。
            "id": f"arb-ledger-{int(time.time() * 1000)}-{secrets.token_hex(2)}",
            "created": _utcnow_iso(),
            "kind": kind,
            "spec": trigger.get("spec"),
            "signal_type": trigger.get("signal_type"),
            "signature": trigger.get("signature"),
            "alert_id": trigger.get("alert_id"),
            "run_id": run_id_eff,
            # 五段结构（LEDGER_SEGMENT_KEYS 同序）
            "scene_snapshot": scene[:4000],
            "forensic_timeline": report.get("forensic_timeline")
            or [
                {
                    "at": trigger.get("enqueued_at"),
                    "event": f"触发入队（source={trigger.get('source')}）",
                },
                {
                    "at": budget.get("started_at"),
                    "event": f"调查 run 启动 run_id={run_id_eff}",
                },
                {"at": budget.get("finished_at"), "event": f"run 终态 kind={kind}"},
            ],
            "root_cause": root[:4000],
            "action_or_upgrade": action_or_upgrade[:4000],
            "evidence_refs": evidence,
            "status_before": str(report.get("status_before") or trigger.get("status_before") or ""),
            "status_after": status_after,
            "budget": dict(budget or {}),
            "failure_reason": failure_reason,
        }
        # 链台账回链（add-escalation-chain-admin-arbiter 3.4）：链驱动路径
        # （trigger 带 _chain_ledger_ids 收集器）把每次写账的条目 id 回填进
        # 触发 dict——链终点上升件据此携带「台账回链」关联键（人工可从上升
        # 件直达每一段调查台账）。
        _chain_ids = trigger.get("_chain_ledger_ids")
        if isinstance(_chain_ids, list):
            _chain_ids.append(str(entry.get("id") or ""))
        path = arbiter_ledger_path(self.project_root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # 原子追加收口（code-review item ddd7e93a1d1d）：台账单行含
            # 4000 字符截断段，UTF-8 常超 4096 字节，文本 open("a") 长行会
            # 裂成多次 raw write，与并发写者（worker 线程 + submit_trigger
            # 复发路径）交错出半行 JSON 被读侧 fail-open 跳过——沿用
            # run_files/维护台账的成文约定（append_run_line：超阈值走二进
            # 制单次 os.write，O_APPEND 下由内核串行化）。
            from core.agent_runner.run_files import append_run_line

            append_run_line(path, entry)
        except OSError as e:
            self._log("error", f"arbiter 台账写入失败（kind={kind}）: {e}")
        return entry

    # ── 告警零噪音分层（4.3）─────────────────────────────────────────

    def _finalize_alert(self, alert_id: str, *, summary: str, evidence_ref: str, run_id: str) -> bool:
        """处置成功：原告警终态化 resolved_by=arbiter（不推送不进 pending）。"""
        try:
            from core.admin_store import AdminStore

            store = AdminStore(self.project_root, self.logger)
            return store.arbiter_resolve(
                alert_id,
                summary=summary,
                evidence_ref=evidence_ref,
                run_id=run_id,
            )
        except Exception as e:
            self._log("error", f"arbiter 告警终态化失败 alert={alert_id}: {e}")
            return False

    def _upgrade_alert(
        self,
        alert_id: str,
        *,
        report: dict,
        recommended: str,
        run_id: str,
        reason: str,
    ) -> bool:
        """升级：裁决包同 alert_id 原位静默更新 + 推 pending（不新增条目）。

        报告进 narrative 槽位（sidecar，model=arbiter）；choices/推荐注入
        原条目；handled 翻回 False 使条目进入 pending 人工队列。
        """
        try:
            # 侧车 IO 已迁至 admin_store（consolidate-alerts-to-ops-page 1.4，
            # adjudication_narrative 模块退役）：报告经 narrative 槽位原位写入
            # 的机制不变
            from core.admin_store import write_narrative_sidecar

            report_text = self._render_upgrade_report(report, reason, run_id)
            write_narrative_sidecar(self.project_root, alert_id, report_text, "arbiter")
        except Exception as e:
            self._log("error", f"arbiter 裁决包 narrative 槽位写入失败 alert={alert_id}: {e}")
        try:
            from core.admin_store import AdminStore

            store = AdminStore(self.project_root, self.logger)
            return store.arbiter_upgrade(
                alert_id,
                summary=str(report.get("summary") or ""),
                recommended_action=recommended,
                run_id=run_id,
                reason=reason,
            )
        except Exception as e:
            self._log("error", f"arbiter 告警原位升级失败 alert={alert_id}: {e}")
            return False

    @staticmethod
    def _render_actions(report: dict) -> str:
        actions = report.get("actions_taken") or []
        if isinstance(actions, str):
            return actions
        return "; ".join(str(a) for a in actions)

    def _render_upgrade_report(self, report: dict, reason: str, run_id: str) -> str:
        """裁决包（报告+选项+推荐）渲染为 narrative 槽位文本。"""
        lines = [
            "## Arbiter 调查报告（裁决包）",
            f"- run: {run_id or 'unknown'}",
            f"- 升级理由: {reason}",
            "",
            "### 调查结论",
            str(report.get("summary") or "（无摘要）"),
            "",
            "### 根因",
            str(report.get("root_cause") or "（未定位）"),
            "",
            "### 处置选项与推荐",
            str(report.get("recommended_action") or "（无推荐——请人工现场裁决）"),
        ]
        refs = report.get("evidence_refs") or []
        if refs:
            lines.append("")
            lines.append("### 证据回链")
            for ref in refs:
                lines.append(f"- {ref}")
        return "\n".join(lines)

    # ── 复发升级（design D6：同签名只自主处置一次）────────────────────

    def _record_recurrence_escalation(
        self,
        *,
        spec: str,
        signal_type: str,
        sig: str,
        severity: str,
        description: str,
        evidence: str,
        alert_id: Optional[str],
        rulings_used: int = 0,
        rulings_cap: int = 2,
        write_ledger: bool = True,
    ) -> None:
        """复现配额耗尽/dead-man 例外：不经 run 直接产裁决包挂新告警升级。

        ``write_ledger=False`` 为同事件双咽喉补绑形态（item 8a294f3ebdc2）：
        首次触发已落 recurrence-escalation 台账，本调用只补做告警原位升级，
        零台账落盘。
        """
        trigger = {
            "spec": spec,
            "signal_type": signal_type,
            "signature": sig,
            "severity": severity,
            "description": description,
            "alert_id": alert_id,
            "source": "recurrence",
            "enqueued_at": _utcnow_iso(),
        }
        if write_ledger:
            self._write_ledger(
                trigger,
                {"run_id": None, "error": ""},
                kind="recurrence-escalation",
                report={
                    "summary": (
                        f"签名 {sig} 复现配额已耗尽（已拍板 {rulings_used}/{rulings_cap}）"
                        "或属 dead-man 永久例外——第 "
                        f"{rulings_used + 1} 次复现强制上升人工。"
                    ),
                    "evidence_refs": [evidence] if evidence else [],
                },
                budget={},
                action_or_upgrade=(
                    f"复现配额耗尽强制升级（拍板 {rulings_used}/{rulings_cap} 后第 "
                    f"{rulings_used + 1} 次复现；dead-man 永久单次例外不复位）"
                ),
                status_after="",
            )
        if alert_id:
            self._upgrade_alert(
                alert_id,
                report={
                    "summary": (
                        f"同签名复现（{sig}）：Arbiter 已拍板 {rulings_used}/{rulings_cap} 次，"
                        "复现配额耗尽（或属 dead-man 永久例外），本次不再自主处置，"
                        "直接升级人工。"
                    ),
                    "root_cause": str(description or "")[:2000],
                    "evidence_refs": [evidence] if evidence else [],
                },
                recommended=str(description or ""),
                run_id="",
                reason="复现配额耗尽/dead-man 例外",
            )

    # ── 框架缺口 gap→todo 路由（add-arbiter-gap-todo-routing）────────────

    def _apply_gaps(self, trigger: dict, report: dict):
        """消费调查报告 gaps 数组（框架缺口发现）逐条记 .fenix/todo.md。

        立项通道已退役（add-arbiter-gap-todo-routing）：arbiter MUST NOT 立项
        ——无写点、无目录物化、无 add_spec，todo.md 即框架缺口的唯一出口。
        缺口记自省队列，由框架自进化车道按既有 todo 消费机制统一评估立项；
        gaps 缺席/为空时本方法零动作。

        切换窗容错（design D1）：旧 prompt 的在飞 run 产出仍带 proposals 数组
        → 记 WARNING 台账（gap-noted 附退役说明）后丢弃，不抛异常不落池。
        """
        run_id = str(trigger.get("run_id") or "")
        legacy = report.get("proposals")
        if isinstance(legacy, list) and legacy:
            self._log(
                "warning",
                f"arbiter 报告带已退役 proposals 字段（切换窗旧 run 产物 "
                f"run_id={run_id}）：记台账留痕后丢弃，不落 todo 不落池",
            )
            self._write_ledger(
                trigger, {"run_id": run_id, "error": ""},
                kind="gap-noted",
                report={
                    "summary": (
                        "报告带已退役 proposals 字段（切换窗旧 prompt 产物）：立项"
                        "通道已退役（add-arbiter-gap-todo-routing），字段内容不落 "
                        "todo 不落池，缺口发现待下次触发重新调查上报。"
                    ),
                    "evidence_refs": [],
                },
                budget={},
                action_or_upgrade=(
                    "旧字段 proposals 已退役：WARNING 台账留痕后丢弃"
                    "（切换窗容错，不静默丢失）"
                ),
                status_after="",
            )
            return
        gaps = report.get("gaps")
        if not isinstance(gaps, list) or not gaps:
            return
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            topic = str(gap.get("topic") or "").strip()
            if not topic:
                continue
            try:
                self._note_gap_todo(trigger, topic, gap)
            except Exception as e:  # noqa: BLE001 —— 单条 gap 失败不连坐其余条目
                self._log(
                    "error", f"arbiter gap 记 todo 失败 topic={topic}: {e}（跳过该条）"
                )

    def _note_gap_todo(self, trigger: dict, topic: str, gap: dict) -> None:
        """单条框架缺口记 todo.md（D2 既有锁与结构契约；D3 轻量同主题去重）。

        - 结构契约：条目渲染复用自省侧 ``SelfReviewScheduler._render_entry_lines``
          单源（标题行 + FIELD_LABELS 四字段嵌套行，与 evolution 解析侧逐字
          一致，不新增第五字段标签）；落「可改进」小节（TODO_SECTIONS 三值
          枚举内，自进化消费面可达）；标题带 ``[arbiter:<签名前8>]`` 来源前缀，
          证据段带触发 run_id，按「可直接起草 SPEC」粒度填写。
        - 锁与写盘：读-去重-插-写整段置于 fs_utils ``with_file_lock``（todo.md
          同一把 .todo.md.lock，与 self_review/evolution/knowledge_backfill
          互斥）内，原子落盘，回写前 HEAD 自愈（todo-ledger-loss-guard 同款
          防护）；git 就地提交在锁外（todo-append-commit-on-write 同款，
          pathspec 限定单文件、失败降级不阻断）。
        - 台账：记入与去重跳过均落 gap-noted（含 topic 与 todo 行号/已存在
          条目指引）。
        """
        run_id = str(trigger.get("run_id") or "")
        entry_lines = self._render_gap_entry_lines(trigger, topic, gap)
        todo_path = Path(self.project_root) / ".fenix" / "todo.md"
        from core.fs_utils import with_file_lock  # noqa: PLC0415 —— 与既有 todo 写方共用同一把锁

        outcome: Dict[str, Any] = {}

        def _do() -> None:
            existing = self._todo_existing_text(todo_path)
            hit = self._todo_topic_hit(topic, existing)
            if hit is not None:
                outcome["dedup_hit"] = hit
                return
            new_text, line_no = _todo_block_insert(
                existing, time.strftime("%Y-%m-%d"), "\n".join(entry_lines)
            )
            from core.fs_utils import atomic_write_text  # noqa: PLC0415 —— 与仓库写点纪律同源

            atomic_write_text(todo_path, new_text)
            outcome["line_no"] = line_no

        with_file_lock(todo_path, _do)
        if "dedup_hit" in outcome:
            hit_title, hit_line = outcome["dedup_hit"]
            self._log(
                "info",
                f"arbiter gap「{topic}」同主题条目已在 todo.md（{hit_title}），跳过记入",
            )
            self._write_ledger(
                trigger, {"run_id": run_id, "error": ""},
                kind="gap-noted",
                report={
                    "summary": (
                        f"框架缺口「{topic}」同主题条目已存在 todo.md（{hit_title}，"
                        f"第 {hit_line} 行），按轻量同主题去重跳过记入。"
                    ),
                    "evidence_refs": [".fenix/todo.md"],
                },
                budget={},
                action_or_upgrade=f"gap 去重跳过（topic={topic}）：已存在条目「{hit_title}」",
                status_after="",
            )
            return
        line_no = int(outcome.get("line_no") or 0)
        try:
            # 写后就地提交（ADR-060 写入点即时提交；锁外执行，untracked/失败
            # 降级不阻断——复用 knowledge_backfill 收口单点，pathspec 限定单文件）
            from core.knowledge_backfill import _commit_todo_after_write  # noqa: PLC0415

            _commit_todo_after_write(self.project_root, f"arbiter gap: {topic}")
        except Exception as e:  # noqa: BLE001 —— 提交降级不阻断记入主流程
            self._log("warning", f"arbiter gap todo 就地提交失败（降级留痕）: {e}")
        where = f"第 {line_no} 行" if line_no else ""
        tail = f" {where}" if where else ""
        self._log(
            "info",
            f"arbiter 框架缺口记 todo topic={topic}{tail}（自进化统一立项）",
        )
        evidence = [".fenix/todo.md"]
        if run_id:
            evidence.append(f".fenix/runs/{run_id}.jsonl")
        self._write_ledger(
            trigger, {"run_id": run_id, "error": ""},
            kind="gap-noted",
            report={
                "summary": (
                    f"框架缺口「{topic}」记入 todo.md{where}"
                    "（自省队列，由自进化车道按既有 todo 消费机制统一评估立项）。"
                ),
                "evidence_refs": evidence,
            },
            budget={},
            action_or_upgrade=f"gap 记 todo（topic={topic}{('，' + where) if where else ''}）",
            status_after="",
        )

    def _render_gap_entry_lines(self, trigger: dict, topic: str, gap: dict) -> List[str]:
        """单条 gap → todo 条目渲染行（复用自省渲染单源，四字段标签逐字一致）。

        字段映射（可立项粒度）：影响=影响面、证据=证据+触发 run_id 来源、
        调查评估=触发信号语境（报告可带 analysis 显式值覆盖）、建议=候选方向。
        """
        from core.self_review import SelfReviewScheduler  # noqa: PLC0415 —— 渲染单源复用

        sig = str(trigger.get("signature") or "")
        run_id = str(trigger.get("run_id") or "")
        evidence_parts = [str(gap.get("evidence") or "").strip()]
        evidence_parts.append(
            f"触发 run_id={run_id or '未知'}（签名 {sig or '未知'}，"
            f"来源 {trigger.get('source') or '未知'}）"
        )
        context = str(trigger.get("description") or "").strip()
        analysis = str(gap.get("analysis") or "").strip() or (
            f"触发信号 {trigger.get('signal_type') or '未知'}"
            f"（spec={trigger.get('spec') or 'global'}）"
            + (f"：{context[:300]}" if context else "")
            + "。Arbiter 调查判定为框架缺口——修复涉及框架代码或产品面变更，"
            "超出处置白名单，记 todo 由自进化统一立项。"
        )
        item = {
            "title": f"[arbiter:{sig[:8] or 'nosig'}] {topic}",
            "impact": str(gap.get("impact") or "").strip(),
            "evidence": "；".join(p for p in evidence_parts if p),
            "analysis": analysis,
            "suggestion": str(
                gap.get("candidates") or gap.get("candidate")
                or gap.get("direction") or ""
            ).strip(),
        }
        return SelfReviewScheduler._render_entry_lines(item) or [f"- {item['title']}"]

    def _todo_existing_text(self, todo_path: Path) -> str:
        """读 todo.md 现状基线；为空/缺失而 HEAD 版非空时自 HEAD 恢复（回写前
        自愈，todo-ledger-loss-guard 同款防护；恢复+写同在调用方所持锁内）。

        todo_head_restore=false（有意清空豁免开关）与 self_review 同源读取。
        """
        from core.config import ConfigLoader  # noqa: PLC0415
        from core.self_review import _load_existing_with_head_rescue  # noqa: PLC0415

        try:
            raw = ConfigLoader.resolve_config(self.project_root)
            restore = bool(
                ConfigLoader.get_self_review_config(raw).get("todo_head_restore", True)
            )
        except Exception:  # noqa: BLE001 —— 配置链故障按缺省开启降级
            restore = True
        return _load_existing_with_head_rescue(
            todo_path, self.project_root, restore,
            self.logger if self.logger is not None else _QuietTodoLogger(),
        )

    @staticmethod
    def _todo_topic_hit(topic: str, existing_text: str) -> Optional[tuple]:
        """轻量同主题去重（D3）：既有未消费条目标题的关键词包含判定。

        解析复用 evolution ``parse_todo_entries`` 单源（只收集未消费、三值
        小节内条目——arbiter 条目落「可改进」，天然在收集面内）；主题词
        （空白/连字符/下划线切分，长度≥2）去来源前缀后任一命中条目标题即
        视为同主题。宁轻勿重（design D3）：误跳少记可由台账人工补，重复记
        可由自省合并。
        Returns: (命中条目标题, todo.md 1 基行号)；未命中返回 None。
        """
        if not existing_text.strip():
            return None
        from core.evolution import parse_todo_entries  # noqa: PLC0415 —— 解析单源

        tokens = [t for t in re.split(r"[\s\-_]+", topic) if len(t) >= 2]
        if not tokens:
            return None
        all_lines = existing_text.splitlines()
        for entry in parse_todo_entries(existing_text):
            title = str(entry.get("title") or "").strip()
            if not title:
                continue
            # 去来源前缀（[arbiter:<sig8>] 等 [] 前缀不参与主题匹配，防
            # 「arbiter」关键字与来源标记自身误命中）
            bare = title
            if bare.startswith("[") and "]" in bare:
                bare = bare.split("]", 1)[1].strip()
            blob = (bare or title).lower()
            if any(t.lower() in blob for t in tokens):
                literal = f"- **{title}**"
                line_no = next(
                    (i + 1 for i, ln in enumerate(all_lines) if ln.strip() == literal),
                    0,
                )
                return (title, line_no)
        return None

    def _resolve_state_machine(self):
        sm = getattr(self, "_state_machine_ref", None)
        return sm

    def set_state_machine(self, sm):
        self._state_machine_ref = sm


class _QuietTodoLogger:
    """todo 回写自愈日志的静默兜底（lane.logger 未装配时；fenixd (component, message) 签名）。"""

    def warning(self, *_args) -> None:
        pass


def _todo_block_insert(text: str, today: str, block: str) -> tuple:
    """把 ``block``（多行条目块）归位插入 todo.md 今日日期节的「可改进」小节下。

    结构与 ``knowledge_backfill._todo_subsection_insert`` 同款：今日节边界 =
    下一个 ``## `` 日期节或文件尾；小节缺失在小节清单尾部补建、日期节缺失
    在文件尾部新建（空文件直接落今日节骨架）。差异仅两点——插入物是多行块
    （块内行原样落位，既有内容不动）；小节名固定「可改进」（
    ``GAP_TODO_SECTION``，evolution 消费面可达）。

    Returns: (回写全文, 块首行在回写全文中的 1 基行号；定位失败为 0)。
    """
    lines = text.splitlines() if text.strip() else []
    header = f"## {today}"
    today_idx = next((i for i, ln in enumerate(lines) if ln.strip() == header), None)
    if today_idx is None:
        if lines:
            lines += ["", header, GAP_TODO_SECTION]
        else:
            lines = [header, "", GAP_TODO_SECTION]
        lines.append(block)
    else:
        end = next(
            (i for i in range(today_idx + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        seg = lines[today_idx:end]
        if not any(ln.strip() == GAP_TODO_SECTION for ln in seg):
            seg = seg + ["", GAP_TODO_SECTION]
        seg.append(block)
        lines[today_idx:end] = seg
    new_text = "\n".join(lines).rstrip("\n") + "\n"
    if not block:
        return new_text, 0
    anchor = block.splitlines()[0]
    line_no = next(
        (i + 1 for i, ln in enumerate(new_text.splitlines()) if ln == anchor), 0
    )
    return new_text, line_no


# ── 模块级单例与装配 ─────────────────────────────────────────────────────

_LANE: Optional[ArbiterLane] = None
_LANE_LOCK = threading.Lock()


def get_lane(project_root=None, logger=None) -> Optional[ArbiterLane]:
    """取车道单例（未装配时惰性建：project_root 缺失返回 None）。"""
    global _LANE
    if project_root is None:
        return _LANE
    with _LANE_LOCK:
        if _LANE is None or _LANE.project_root != Path(project_root):
            _LANE = ArbiterLane(project_root, logger)
        elif logger is not None and _LANE.logger is None:
            _LANE.logger = logger
        return _LANE


def set_lane(lane: Optional[ArbiterLane]) -> None:
    """测试注入口：直接替换单例（None 清空）。"""
    global _LANE
    with _LANE_LOCK:
        _LANE = lane


def reset_lane() -> None:
    set_lane(None)


# ── state_machine 咽喉回调解耦（1.1 的注册端）────────────────────────────

def install_freeze_hook() -> None:
    """把 freeze_for_human 咽喉的链/Arbiter 派发回调注册进 state_machine。

    幂等（重复安装零副作用）；回调解耦——state_machine 不 import 本模块，
    只持有可调用。add-escalation-chain-admin-arbiter 1.3：咽喉改道链优先
    ——链可用（arbiter.enabled ∧ 车道装配完备）且信号非黑名单时入链头
    （链内 dedup 与告警咽喉同签名 dedup 单源：冻结先入队、告警随后 dedup
    零落盘）；链失能/黑名单命中回落既有 Arbiter 直派（arbiter.enabled=false
    时回调内部短路 disabled 零写入，关闭态零侵扰语义不变）。
    """
    from core import state_machine as _sm

    def _on_machine_freeze(**kwargs):
        lane = get_lane()
        if lane is None:
            return
        # 链优先派发（链单例以车道装配为锚——project_root/logger 同源）。
        # 链 absent/失能/黑名单一律回落直派，判定异常同样回落（冻结派发
        # 故障不回滚冻结本身，与告警容错同口径）。
        try:
            from core.pm_engine.escalation_chain import get_chain

            chain = get_chain(lane.project_root, lane.logger)
        except Exception:
            chain = None
        if chain is not None:
            try:
                outcome = chain.submit_entry(
                    spec=str(kwargs.get("spec_name") or "global"),
                    signal_type=str(kwargs.get("signal_type") or ""),
                    severity=str(kwargs.get("severity") or "major"),
                    description=str(kwargs.get("description") or ""),
                    evidence=str(kwargs.get("evidence") or ""),
                    recommended_action=str(kwargs.get("recommended_action") or ""),
                    source="freeze_for_human",
                )
                if outcome in ("queued", "deduped"):
                    return  # 已入链（告警咽喉随后的同签名触发将 dedup 零落盘）
                # blacklisted/disabled：回落既有直派（disabled 时下方
                # submit_trigger 亦短路 disabled，零写入）
            except RuntimeError as e:
                # 链队列满显式报错：留痕回落直派（不吞成「已入链」）
                if lane.logger is not None:
                    lane.logger.warning(
                        COMPONENT, f"处置链冻结触发登记失败（回落直派）: {e}"
                    )
            except Exception as e:
                if lane.logger is not None:
                    lane.logger.warning(
                        COMPONENT, f"处置链冻结触发异常（回落直派，非阻塞）: {e}"
                    )
        try:
            lane.submit_trigger(
                spec=str(kwargs.get("spec_name") or "global"),
                signal_type=str(kwargs.get("signal_type") or ""),
                severity=str(kwargs.get("severity") or "major"),
                description=str(kwargs.get("description") or ""),
                evidence=str(kwargs.get("evidence") or ""),
                recommended_action=str(kwargs.get("recommended_action") or ""),
                alert_id=None,  # 冻结先于告警落盘：alert 后由告警咽喉补绑
                source="freeze_for_human",
            )
        except RuntimeError as e:
            # 排队登记失败显式留痕（吞掉会变成「看起来注册了其实没排上」）
            if lane.logger is not None:
                lane.logger.warning(COMPONENT, f"arbiter 冻结触发登记失败: {e}")
        except Exception as e:  # 触发面故障不回滚冻结本身（与告警容错同口径）
            if lane.logger is not None:
                lane.logger.warning(COMPONENT, f"arbiter 冻结触发异常（非阻塞）: {e}")

    _sm.set_arbiter_freeze_hook(_on_machine_freeze)


def freeze_hook_installed() -> bool:
    """消费预演自检用：state_machine 咽喉回调是否已注册（真源在 state_machine）。"""
    from core import state_machine as _sm

    return _sm.get_arbiter_freeze_hook() is not None
