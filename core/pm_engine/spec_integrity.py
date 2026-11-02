"""spec_integrity.py — 派发前内容完整性闸门（add-spec-content-integrity-gate）。

空 spec 目录（`spec/changes/<spec>/` 无实质内容）仍会被派发 implementer 盲目
实现、烧满实现预算后才被预算闸门拦下——scheduling-showcase 夹具实证 c-sched-set /
c-sched-clear 两条空占位 spec 各盲跑 6 个 run。本模块在派发前提供「内容」维度
闸门，与既有「次数」维度闸门（ImplBudget._check_impl_budget_exhausted）同层
并列（design D1）。

设计要点（design D2/D3/D4/D5）：
- ``spec_has_content`` 纯函数：`proposal.md` / `design.md` / `tasks.md` /
  `specs/**/*.md` 任一存在即视为有内容，宽松到覆盖全部合法形态（早期 draft
  可能只有 proposal），同时拦得住「空目录 / 只有无关文件」的异常；
- 读目录 IO 异常保守放行（记 WARNING 不误伤）：闸门的目标是拦空 spec，
  不是卡死派发；
- ``check_spec_content_missing`` 闸门方法：命中即 blocked + 结构化 frozen 标记
  + human-escalation 告警（signal_type=spec_content_missing, severity=major），
  复用预算闸门的冻结范式；已是 blocked 幂等不重复告警但仍拒绝重派。
  alert-noise-governance 分类修正（2026-09-23）：入口对终态（done/pushed，
  含 spec 文本 archived 拼写）短路——已交付/归档 spec 不因目录内容缺失被
  反向冻结（c-sched-set 实证：实现已合并、验证 25/25 通过，外部 STATE 重置
  打回 ready 后仍被按「空 spec」冻结并挂反向 major 告警）；目录仅存
  verification-report.md 时改产独立信号 ``spec_delivered_no_content``（不
  冻结、文案引导人工裁决，自带幂等短路防告警风暴），无验证报告才走既有
  冻结路径。
  frozen 标记不可省（scheduling-showcase 夹具回归）：admin_monitor 的
  blocked_stuck 豁免只看 ``frozen`` 字段 / error 前缀 ``frozen:`` / error 含
  「用户指令」三者，闸门自有文案一条都不占——缺标记时冻结满
  ``admin.escalation_cooldown_minutes``（默认 60 分钟）即自动召唤一次
  Administrator agent run（夹具实证两次：admin-c-sched-set-1789106554 /
  admin-c-sched-clear-1789199472，309KB / 348KB 转写纯浪费）。同层先例为
  env 阻塞冻结（verification.py）：同样写 ``frozen: True`` + 自有文案。

模块落点独立文件（design D5）：与 budget.py 同层并列，未来若需按项目白名单
扩展判定不污染预算计数逻辑。
"""

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from core.timelib import parse_ts

# 可传播到 fenixd 已挂载 handler 的结构化日志器（fix-robustness-edge-cases 3.1：
# 收敛旁路裸 getLogger("pm_engine")，保证 WARNING 落入 fenixd.log）
_logger = logging.getLogger("fenixd.pm_engine.spec_integrity")

# 「已交付未落盘」独立信号（alert-noise-governance 1.2）：目录无认可内容但
# 存在 verification-report.md 时，替代 spec_content_missing 的 signal_type。
# 闭环条件映射见 core/alert_lifecycle.py（spec_delivered_adjudicated）。
SPEC_DELIVERED_NO_CONTENT_SIGNAL = "spec_delivered_no_content"

# 「已交付未落盘」判定凭据：验证链落盘的验证报告（core/verify_report.py
# 写入 spec/changes/<spec>/verification-report.md）。它是验证产物而非 spec
# 起草内容，故只作分类凭据、不进 spec_has_content 认可名单（见其注释）。
_DELIVERED_REPORT_FILENAME = "verification-report.md"

# ── 存量幽灵条目结构性清退（fix-legacy-ghost-spec-entry-reclaim）──────
# 常量名单点定义（对齐 IMPL_RUN_BUDGET_USED_FIELD 家族惯例：模块级大写常量
# + 注释块，pm_engine 与测试断言同源引用，避免字面量漂移）：
# - GHOST_ENTRY_FRESHNESS_MINUTES：幽灵指纹新鲜度豁免窗（design D2 条件 3）
#   ——条目 created 距今不足该窗的豁免不清退：物化与注册间存在理论竞态窗口，
#   新条目不立即清退、留待下一轮对账（零误杀取向）。
# - GHOST_RECLAIM_LEDGER_KIND：台账留痕 kind 字面量（写侧与测试断言同源）。
# - GHOST_RECLAIM_SIGNAL_TYPE：聚合告警 signal_type（幂等防重判据同源；
#   未注册闭环条件 → 永不自动闭环，人工 handled 收口，保守默认）。
# - GHOST_RECLAIM_LEDGER_FILENAME：台账落盘文件名（<project>/.fenix/ 下
#   append-only jsonl，对齐 maintenance_log.jsonl / arbiter_ledger.jsonl
#   既有台账先例；.fenix 运行时目录不入库）。
GHOST_ENTRY_FRESHNESS_MINUTES = 30
GHOST_RECLAIM_LEDGER_KIND = "ghost-entry-reclaimed"
GHOST_RECLAIM_SIGNAL_TYPE = "ghost_entry_reclaimed"
GHOST_RECLAIM_LEDGER_FILENAME = "ghost_reclaim_ledger.jsonl"

# - _GHOST_GIT_PROBE_BUDGET_S：单轮对账 git 探测总量预算（code-review
#   f07703eed1e6）——detect_ghost_entries 在循环内逐条串行 spawn
#   ``git log --all``（timeout=15/次），存量异常项目（大量空占位 spec）叠加
#   git 缺失/仓库异常时每条都等满超时，单轮最坏耗时 = 候选数 × 15s，经
#   full_scan 周期调用拉长整轮扫描。累计探测耗时超预算后剩余候选本轮跳过
#   （保守不清退，下轮对账继续）。实际仓库 git 正常时单次毫秒级，预算仅
#   封顶异常形态。
_GHOST_GIT_PROBE_BUDGET_S = 30.0

# spec 名路径安全白名单（code-review bf17492bd055）：STATE.md 为人工可编辑
# 数据源，spec_name 会被直接拼进 spec/changes/<spec_name>/ 路径；放行路径
# 分隔符或 ``..`` 成分会令内容判定探测 changes 之外的目录（越界目录恰有
# 内容时误放行派发、或反向误冻结）。白名单比 core/spec_naming.py 的 kebab
# 权威正则宽松（不绑定命名契约、只卡路径安全），合法 kebab 名恒通过。
_SPEC_NAME_PATHSAFE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_safe_spec_name(spec_name) -> bool:
    """spec 名路径合法性：仅单个安全路径成分，杜绝 ``..`` 与分隔符越界。"""
    if not isinstance(spec_name, str) or _SPEC_NAME_PATHSAFE_RE.match(spec_name) is None:
        return False
    # 正则已排除路径分隔符与空名；再排除 ``..`` 成分与前导点隐藏名
    return not spec_name.startswith(".") and ".." not in spec_name


def spec_has_content(project_root, spec_name: str) -> bool:
    """判定 spec 目录是否含实质内容（纯函数，design D2）。

    Args:
        project_root: 项目根（Path 或可转 Path 的路径）。
        spec_name: spec 名，对应 ``spec/changes/<spec_name>/`` 目录。

    Returns:
        True = 有实质内容（或读目录异常保守放行）；
        False = 目录不存在 / 目录为空 / 无常驻 spec 内容文件 /
        spec 名含非法路径成分（不拼越界路径判定，保守按无内容）。
    """
    if not _is_safe_spec_name(spec_name):
        # STATE.md 人工可编辑（bf17492bd055）：含 ``..``/路径分隔符的名字不拼
        # 路径探测，保守按「无内容」处理——闸门下游既有语义接管（blocked 短路/
        # 终态豁免交派发层状态机拒绝/非终态冻结），不做越界冻结或放行判定。
        _logger.warning(
            "spec 名含非法路径成分，按无内容保守处理: %r",
            spec_name,
        )
        return False
    spec_dir = Path(project_root) / "spec" / "changes" / spec_name
    try:
        if not spec_dir.is_dir():
            return False
        # 四选一判定：proposal / design / tasks / specs/**/*.md 任一存在即满足。
        # alert-noise-governance 1.3：verification-report.md 刻意 NOT 进认可
        # 名单——它是验证链落盘的产物（core/verify_report.py），不是 spec 起
        # 草内容。若纳入，外部 STATE 重置把已交付 spec 打回 ready 后，派发
        # 内容判据即被遗留的报告文件「凭空满足」，实现 run 会对已合并成果盲
        # 目重实现（09-12 实证：06:33Z 重置 → 盲目重实现 05:42Z 已合并成果）。
        # 报告在场走 check_spec_content_missing 的「已交付未落盘」分类分支。
        for name in ("proposal.md", "design.md", "tasks.md"):
            if (spec_dir / name).is_file():
                return True
        specs_dir = spec_dir / "specs"
        if specs_dir.is_dir():
            # specs/ 子目录递归扫 *.md：覆盖只有 specs/ 无三文档的形态
            # is_file() 过滤：rglob 同时命中名为 *.md 的目录，空目录不可伪造有内容
            if next((p for p in specs_dir.rglob("*.md") if p.is_file()), None) is not None:
                return True
        return False
    except OSError:
        # 读目录异常保守放行：权限/临时不可达下宁可放行让预算闸门兜底
        _logger.warning(
            "读取 spec 目录失败（保守放行）: %s",
            spec_dir,
        )
        return True


def ghost_reclaim_ledger_path(project_root) -> Path:
    """幽灵清退台账路径（<project>/.fenix/ghost_reclaim_ledger.jsonl）。"""
    return Path(project_root) / ".fenix" / GHOST_RECLAIM_LEDGER_FILENAME


def git_path_has_commits(project_root, spec_name: str) -> bool:
    """git 全历史对 ``spec/changes/<spec_name>`` 是否有过提交（design D2 条件 2）。

    判据即 design 字面：``git -C <project_root> log --all --
    spec/changes/<name>`` 输出为空 = 全历史零提交。已归档/曾提交后目录被误删
    的条目历史仍在（输出非空），不会命中指纹——只清退「从未立项过」的裸注册
    产物。

    Returns:
        True = 有提交（指纹条件 2 不成立，不清退）；
        False = 零提交（条件成立）；
        git 不可用 / 超时 / 非零退出（含非 git 目录）时保守返回 True——
        「无法证明零提交」不得作为清退依据（零误杀取向）。
    """
    import subprocess

    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "log",
                "--all",
                "--",
                f"spec/changes/{spec_name}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # git 缺失（FileNotFoundError）/超时等：保守按「有历史」不清退
        return True
    if proc.returncode != 0:
        # 非 git 目录 / 裸仓库无提交等：输出空但失败原因不可辨，保守不清退
        return True
    return bool(proc.stdout.strip())


def entry_age_minutes(entry, now: datetime) -> "float | None":
    """STATE 条目 created 距今分钟数；created 缺失/非法返回 None（不可判龄）。"""
    created = parse_ts(str(entry.get("created") or ""))
    if created is None:
        return None
    return (now - created).total_seconds() / 60.0


class SpecIntegrityGate:
    """内容完整性闸门组件（design D1/D4，与 ImplBudget 同型）。

    ``_pm`` 门面回引：组件内非自有状态/方法经 ``self._pm.X`` 访问
    （refactor-core-packages design D3 规则 3），保住门面实例上的测试补丁缝。
    """

    def __init__(self, pm):
        self._pm = pm

    def check_spec_content_missing(self, spec_name: str) -> bool:
        """派发前校验 spec 目录有无实质内容（design D1/D4）。

        无内容且状态非 blocked 时执行冻结处置：``update_spec(status=blocked,
        frozen=True, error=内容缺失)`` + ``_send_human_escalation_alert(
        signal_type=spec_content_missing, severity="major")``。冻结标记使
        admin_monitor 的 blocked_stuck 豁免生效（自动链路对 status 的改写亦被
        StateMachine 的冻结保护剥离），唯一出路是补内容后人工 unfreeze_spec。

        alert-noise-governance 分类修正：
        - 终态（done/pushed/archived）短路——不冻结、不出 spec_content_missing；
        - 目录仅存 verification-report.md 走「已交付未落盘」分类——不冻结、
          改产 spec_delivered_no_content 引导人工裁决，派发仍被拦（返回 True）。

        Returns:
            True = 已拦（spec 因内容缺失被冻结 / blocked 幂等 / 已交付未落盘）；
            False = 有内容 / 终态豁免 / IO 异常保守放行，调用方继续派发。
        """
        if spec_has_content(self._pm.project_root, spec_name):
            return False

        # [fenix-ignore:e55afea2a5a6] read_one 经 read_all → _normalize_entries 已过滤非 dict 条目（core/state_machine.py read_all 防御层），返回值只可能是 dict 或 None（None 由 or {} 兜底），entry.get 不会抛 AttributeError
        entry = self._pm.state_machine.read_one(spec_name) or {}
        status = entry.get("status")
        if status == "blocked":
            # 已冻结（可能由本闸门或其它闸门触发）：不重复告警，但仍阻止重派
            return True

        # 终态口径（alert-noise-governance 1.1）复用 alert_lifecycle 权威常量
        # （done/pushed，另含 spec.md 场景文本的 archived 拼写，向前兼容），
        # 不再手抄副本——权威集合扩容时本闸门自动跟随，避免口径漂移。
        from core.alert_lifecycle import DELIVERED_ADJUDICATED_TERMINAL_STATUSES as _TERMINAL
        if status in _TERMINAL:
            # 终态豁免（alert-noise-governance 1.1，design D1）：已交付/归档
            # spec 不因目录内容缺失被反向冻结、不产 spec_content_missing——
            # 外部 STATE 重置把已交付 spec 打回后按「空 spec」冻结，处置方向
            # 与事实相反（c-sched-set 实证：实现已合并、验证 25/25 通过仍被
            # 冻结挂 major 告警，gate-delivered-spec-exemption 登记链）。
            # **终态豁免不等于放行派发**：本分支只免「冻结 + 告警」处置，不
            # 新增任何派发放行语义——非终态「已交付未落盘」目录的派发拦截由
            # 下方分类分支与 spec_has_content 判据承担（返回 True）；终态 spec
            # 无论有无 verification-report.md 均在本分支短路、到不了下方分类
            # 分支（该分类分支仅服务非终态），出现在派发队列本身属异常，由
            # 派发层状态机语义管辖（非法 transition 被拒），不由本闸门越权代管。
            self._pm.logger.debug(
                "pm_engine",
                f"内容完整性闸门终态豁免：'{spec_name}' status={status}，"
                f"目录无认可内容但不冻结不告警（已交付/归档 spec）",
            )
            return False

        if self._has_delivered_report(spec_name):
            return self._handle_delivered_no_content(spec_name)

        # fix-blocked-freeze-classification 3.1：收敛到 freeze_for_human 单一
        # 入口（frozen + 人工升级告警成对写入），消除「各站点各自记得成对」
        # 的漂移面。error 文案原样保留（长文案，不强制统一前缀）。
        self._pm.state_machine.freeze_for_human(
            spec_name,
            error=(
                f"SPEC 内容缺失：spec/changes/{spec_name}/ 目录不含 "
                f"proposal.md/design.md/tasks.md/specs/**/*.md 任一实质内容，"
                f"已中止派发并冻结，需人工补全 spec 内容后解冻"
            ),
            signal_type="spec_content_missing",
            severity="major",
            description=(
                f"'{spec_name}' 的 spec/changes/{spec_name}/ 目录为空或无实质"
                f"内容，已中止派发并冻结等待人工处置"
            ),
            evidence=(
                f"spec={spec_name}; 判定=spec_has_content False；"
                f"缺失文件=proposal.md/design.md/tasks.md/specs/**/*.md 全缺"
            ),
            recommended_action=(
                "补全 spec/changes/<spec_name>/ 内容（proposal.md/design.md/"
                "tasks.md/specs/*.md 任一即可）后解冻 spec；补内容后该告警将"
                "被自动闭环（spec_content_missing → spec_terminal_or_unblocked）"
            ),
            alert_callback=self._pm._send_human_escalation_alert,
        )
        self._pm.logger.error(
            "pm_engine",
            f"内容完整性闸门命中：'{spec_name}' 空 spec，冻结为 blocked",
        )
        return True

    def _has_delivered_report(self, spec_name: str) -> bool:
        """spec 目录是否存在验证链落盘的 verification-report.md（分类凭据）。"""
        if not _is_safe_spec_name(spec_name):
            # 同 spec_has_content（bf17492bd055）：非法名不拼路径，保守按
            # 「无凭据」走既有冻结路径（与下方 OSError 分支同一缺省方向）
            _logger.warning(
                "spec 名含非法路径成分，按无验证报告保守处理: %r",
                spec_name,
            )
            return False
        try:
            return (
                Path(self._pm.project_root)
                / "spec"
                / "changes"
                / spec_name
                / _DELIVERED_REPORT_FILENAME
            ).is_file()
        # [fenix-ignore:73c76dafba33] 非死代码：is_file 仅吞 ENOENT/ENOTDIR/EBADF/ELOOP，EACCES/EIO 等其余 OSError 仍向外抛出，本分支可达
        except OSError:
            return False  # 探测异常按「无凭据」走既有冻结路径（保守分类）

    def _handle_delivered_no_content(self, spec_name: str) -> bool:
        """「已交付未落盘」分类（alert-noise-governance 1.2，design D2）。

        目录无认可内容但存在 verification-report.md——已交付 spec 被外部
        STATE 重置，或废弃半成品。不冻结（处置方向与「空 spec」相反：冻结
        会把待裁决 spec 封进 blocked，人工裁决上下文即丢失），改产独立信号
        ``spec_delivered_no_content`` 引导裁决：补 tasks.md 归档凭据，或明确
        废弃后置终态。派发仍被拦（返回 True，spec_has_content 判据不动），
        最坏多一条待裁决告警、无预算损失路径。

        幂等短路（MUST）：本分支放弃冻结即失去「status==blocked → 下次短路」
        的既有幂等保护，而 SPEC 状态停在 ready 会被恢复精触发（60s）与
        full_scan 反复命中——已存在同 spec 同 signal_type 未处理告警时不再
        追加（对齐 admin_monitor._throttled 的「已存在未处理升级告警」判据），
        否则每分钟追加一条 major 告警。
        """
        try:
            from core.admin_store import AdminStore

            store = AdminStore(self._pm.project_root, self._pm.logger)
            if store.unhandled_for(spec_name, SPEC_DELIVERED_NO_CONTENT_SIGNAL) is not None:
                # 幂等命中：告警在案待裁决，仅保持派发拦截；重复命中日志降
                # debug（恢复精触发 60s 一轮，info 级即刷屏）
                self._pm.logger.debug(
                    "pm_engine",
                    f"内容完整性闸门重复命中（spec_delivered_no_content 告警"
                    f"在案）：'{spec_name}' 保持派发拦截，不重复告警",
                )
                return True
        except Exception as e:
            # 幂等预检失败不阻断告警写入（宁多一条不漏告警）；写入侧
            # _send_human_escalation_alert 自带 try/except 容错
            self._pm.logger.warning(
                "pm_engine",
                f"spec_delivered_no_content 幂等预检失败 '{spec_name}': {e}",
            )

        self._pm.logger.warning(
            "pm_engine",
            f"内容完整性闸门命中（已交付未落盘）：'{spec_name}' 仅存 "
            f"verification-report.md、无认可内容，产 spec_delivered_no_content"
            f"待人工裁决（不冻结）",
        )
        # 经统一告警入口写入（trigger 由 alert_lifecycle.build_trigger 按
        # signal_type 推导为 spec_delivered_adjudicated，调用点无需显式传）
        self._pm._send_human_escalation_alert(
            spec_name=spec_name,
            signal_type=SPEC_DELIVERED_NO_CONTENT_SIGNAL,
            severity="major",
            description=(
                f"'{spec_name}' 的 spec/changes/{spec_name}/ 目录仅存 "
                f"verification-report.md、无认可内容（proposal.md/design.md/"
                f"tasks.md/specs/**/*.md 全缺）——疑似已交付 spec 被外部重置"
                f"或废弃半成品。未冻结，等待人工裁决"
            ),
            evidence=(
                f"spec={spec_name}; 判定=spec_has_content False 且 "
                f"{_DELIVERED_REPORT_FILENAME} 在场；处置=不冻结、产独立信号"
                f"引导裁决（区别于 spec_content_missing 的冻结路径）"
            ),
            recommended_action=(
                "二选一裁决：① 按已交付认定补 tasks.md 归档凭据（或写处置记"
                "录说明预期空 spec）后人工 handled 收口；② 确认废弃则将 spec "
                "置终态（done/archived），本告警经 spec_delivered_adjudicated "
                "条件自动闭环。裁决前派发持续被拦，不会盲目重实现"
            ),
        )
        return True

    # ── 存量幽灵条目结构性清退（fix-legacy-ghost-spec-entry-reclaim）──

    def _spec_has_active_worktree(self, spec_name: str) -> bool:
        """归属 worktree 是否仍活跃（框架锚定豁免探测，code-review 216a09577e1a）。

        ``has_active_worktree`` 用 ``is True`` 严格判定（对齐 recovery.py D1
        ``has_pending_merge`` 的 mock 替身回归先例）：既有夹具的
        ``agent_runner`` 为 MagicMock（``bool(MagicMock()) is True``），裸真值
        判定会把替身误判为「worktree 活跃」而豁免全部候选、令指纹判定整体
        失效；生产实现（worktree_manager.lifecycle）恒返回真实 bool。

        Returns:
            True = 仍有活跃 worktree（条目仍被框架锚定，豁免清退）；
            探测链任一环节缺失/异常按 False 保守处置（implementer_run/branch
            锚点字段豁免仍兜底，不阻断本轮对账）。
        """
        try:
            wm = getattr(
                getattr(self._pm, "agent_runner", None),
                "worktree_manager",
                None,
            )
            if wm is not None and wm.has_active_worktree(spec_name) is True:
                return True
        except Exception:
            pass
        return False

    def detect_ghost_entries(self, now=None) -> dict:
        """幽灵指纹判定（design D2 三条件 AND，零误杀取向）。

        对 STATE 全部条目逐条判定，任何一条不成立 → 不命中（维持既有链路，
        零日志噪音）：

        0. 非法路径成分 spec 名（``_is_safe_spec_name`` 拒绝，与
           spec_has_content 同谓词保守语义）：不进命中清单、另入跳过清单待
           告警（task 1.1）；
        1. 终态豁免：终态条目（权威口径复用 alert_lifecycle 终态常量，含
           design D2 字面的 ``pushed``——状态机唯一终态）不参与判定；
        2. ``spec_has_content(project_root, name)`` 为 True 不命中：物化过
           最小 proposal 的条目（7f7ee45e2 范式）恒为 True，天然不命中；
        3. 新鲜度豁免：created 距今不足
           ``GHOST_ENTRY_FRESHNESS_MINUTES``（30 分钟）不命中；created 缺失
           或不可解析（判龄失败）保守视为未过窗、不清退；
        4. 框架锚定豁免（code-review 216a09577e1a）：``implementer_run`` /
           ``branch`` 锚点非空、或归属 worktree 仍活跃
           （``_spec_has_active_worktree``）的条目不参与判定、入 skipped
           留痕——「无内容 + 零提交 + 超窗」对在途实施中的 spec 同样可能
           成立（旧数据或绕过内容闸门的外部写入流程 + 目录被清空），结构性
           清退会孤儿化在飞 run 并丢失 STATE 锚点；
        5. ``git_path_has_commits`` 为 True（git 全历史有提交）不命中；
           git 探测受单轮总量预算约束（``_GHOST_GIT_PROBE_BUDGET_S``，
           code-review f07703eed1e6）：累计耗时超预算后剩余候选本轮跳过
           （保守不清退，下轮对账继续），避免候选多且 git 异常时单轮对账
           耗时无上界。

        三条件（2∧3∧5）同时成立且未触发 1/4 豁免才判幽灵——与幽灵定义
        （「从未物化立项」）重合，误杀前提收敛为「目录从未存在且从未提交
        且注册已超 30 分钟且已不被框架锚定」。

        Returns:
            ``{"hits": [...], "skipped": [...], "anchored": [...]}``：hits
            每项含 spec 名、命中时状态与三项指纹证据（created/age、目录
            探测、git log 空输出）；skipped 为保守跳过名清单（非法路径成分
            待人工 + 框架锚定豁免，不清退），anchored 子清单单列后者供告警
            侧区分措辞并豁免升级。
        """
        now = now or datetime.now(timezone.utc)
        hits: list = []
        skipped: list = []
        anchored: list = []
        git_probe_spent_s = 0.0
        git_probe_over_budget = False
        # [fenix-ignore:e55afea2a5a6] read_one 经 read_all → _normalize_entries 已过滤非 dict 条目（core/state_machine.py read_all 防御层），read_all 同源；entry.get 不会抛 AttributeError（非 dict 再防御同 check_blockers 先例）
        all_specs = self._pm.state_machine.read_all() or {}
        # 终态口径复用 alert_lifecycle 权威常量（done/pushed + spec 文本
        # archived 向前兼容拼写），不手抄副本——与 check_spec_content_missing
        # 同源引用，权威集合扩容时自动跟随。
        from core.alert_lifecycle import (
            DELIVERED_ADJUDICATED_TERMINAL_STATUSES as _TERMINAL,
        )

        for name, entry in all_specs.items():
            if not isinstance(entry, dict):
                continue
            if not _is_safe_spec_name(name):
                # 非法路径成分（``..``/分隔符/隐藏名）：保守跳过不清退，
                # 只入跳过清单待人工告警（design D3 / spec Requirement 2）
                skipped.append(name)
                continue
            status = entry.get("status")
            if status in _TERMINAL:
                # 终态豁免（design D2：终态 pushed 豁免）
                continue
            if spec_has_content(self._pm.project_root, name):
                # 条件 1 不成立：有实质内容，静默跳过（零日志噪音）
                continue
            age = entry_age_minutes(entry, now)
            if age is None or age < GHOST_ENTRY_FRESHNESS_MINUTES:
                # 条件 3 不成立：新条目豁免 / 判龄失败保守不清退
                continue
            # 条件 4 框架锚定豁免（216a09577e1a）：锚点判定零 IO，置于 git
            # 子进程探测之前——命中即免一次 ``git log --all``（同步节约
            # f07703eed1e6 的探测预算）。可空字段解析（StateParser nullable
            # 归一清单）保证 implementer_run/branch 读回 None 或真实值，
            # ``str(x or "")`` 口径对齐 budget 锚点读取先例。
            if (
                str(entry.get("implementer_run") or "").strip()
                or str(entry.get("branch") or "").strip()
                or self._spec_has_active_worktree(name)
            ):
                # 仍被派发链路锚定（在途实施中属正常形态）：不清退，入既有
                # skipped 留痕清单；仅框架锚定豁免不升级人工（见
                # _send_ghost_reclaim_alert 的 anchored 区分）
                skipped.append(name)
                anchored.append(name)
                continue
            if git_probe_over_budget:
                # 条件 5 预算已耗尽：剩余候选本轮跳过探测、保守不清退，下轮
                # 对账继续（耗尽日志在越过阈值时记一次，见下）
                continue
            _probe_started = time.monotonic()
            has_commits = git_path_has_commits(self._pm.project_root, name)
            git_probe_spent_s += time.monotonic() - _probe_started
            if git_probe_spent_s > _GHOST_GIT_PROBE_BUDGET_S:
                git_probe_over_budget = True
                self._pm.logger.info(
                    "pm_engine",
                    f"幽灵对账 git 探测累计耗时 {git_probe_spent_s:.1f}s 超预算 "
                    f"{_GHOST_GIT_PROBE_BUDGET_S:.0f}s，本轮剩余候选跳过探测"
                    f"（保守不清退，下轮对账继续）",
                )
            if has_commits:
                # 条件 5 不成立：git 全历史有提交（曾立项，目录可能被误删）
                continue
            hits.append(
                {
                    "spec": name,
                    "status": status,
                    "created": str(entry.get("created") or ""),
                    "age_minutes": round(age, 1),
                    "dir_evidence": (
                        f"spec/changes/{name}/ 无实质内容"
                        "（proposal.md/design.md/tasks.md/specs/**/*.md 全缺）"
                    ),
                    "git_evidence": (
                        f"git -C {self._pm.project_root} log --all -- "
                        f"spec/changes/{name} 输出为空（全历史零提交）"
                    ),
                }
            )
        return {"hits": hits, "skipped": skipped, "anchored": anchored}

    def reclaim_ghost_entries(self) -> dict:
        """幽灵条目对账清退入口（design D3/D4：先收集全部命中再批量执行）。

        配置开关 ``gates.ghost_entry_reclaim``（默认 on，task 2.2）关闭时
        直接返回零副作用。单轮至多一条聚合告警列出全部清退/跳过条目
        （替代逐条 freeze→escalate 的人工通道）；防重对齐
        ``_handle_delivered_no_content`` 的未处理告警先例（本文件
        spec_delivered_no_content 分支——同指纹未处理告警在场时不重复告警）。

        Returns:
            ``{"enabled", "reclaimed", "skipped", "alerted"}``；reclaimed 为
            实际完成 remove_spec + 台账留痕的命中清单。
        """
        if not self._pm._get_config("gates.ghost_entry_reclaim", True):
            # 开关 off：对账入口直接返回（design D4），零判定零副作用
            return {
                "enabled": False,
                "reclaimed": [],
                "skipped": [],
                "alerted": False,
            }

        verdict = self.detect_ghost_entries()
        hits = verdict["hits"]
        skipped = verdict["skipped"]
        # 框架锚定豁免子清单（216a09577e1a）：skipped 成员，告警侧据此区分
        # 措辞且仅锚定豁免的轮次不升级人工
        anchored = verdict.get("anchored") or []
        if not hits and not skipped:
            # 零命中：幂等空转（零副作用、零日志噪音——design D4）
            return {
                "enabled": True,
                "reclaimed": [],
                "skipped": [],
                "alerted": False,
            }

        reclaimed: list = []
        for hit in hits:
            name = hit["spec"]
            if not self._pm.state_machine.remove_spec(name):
                # 竞争消失（他写者已移除）：不算本轮清退，不留痕
                continue
            reclaimed.append(hit)
            self._append_ghost_reclaim_ledger(name, hit)

        alerted = self._send_ghost_reclaim_alert(reclaimed, skipped, anchored)
        return {
            "enabled": True,
            "reclaimed": reclaimed,
            "skipped": skipped,
            "alerted": alerted,
        }

    def _append_ghost_reclaim_ledger(self, name: str, hit: dict) -> None:
        """逐条台账留痕（design D3）：kind=ghost-entry-reclaimed + 三项证据。

        append-only jsonl（对齐 maintenance_ledger 的 ``append_run_line``
        原子追加约定）；写入失败不阻断清退主流程（留痕尽力，宁清退不回滚
        ——移除本身已原子完成，台账失败仅记 WARNING）。
        """
        from core.agent_runner.run_files import append_run_line
        from core.timelib import now_utc, to_storage

        record = {
            "ts": to_storage(now_utc()),
            "kind": GHOST_RECLAIM_LEDGER_KIND,
            "spec": name,
            "status_at_reclaim": hit.get("status"),
            "evidence": {
                "created": hit.get("created"),
                "age_minutes": hit.get("age_minutes"),
                "dir_probe": hit.get("dir_evidence"),
                "git_log": hit.get("git_evidence"),
            },
        }
        try:
            path = ghost_reclaim_ledger_path(self._pm.project_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            append_run_line(path, record)
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine",
                f"幽灵清退台账写入失败（清退已生效，留痕缺失）'{name}': {e}",
            )

    def _send_ghost_reclaim_alert(
        self, reclaimed: list, skipped: list, anchored=()
    ) -> bool:
        """单条聚合告警（design D3）：列出本轮全部清退/跳过条目与证据。

        防重（幂等）：存在任一同 signal_type 未处理升级告警时不再追加
        （对齐 _handle_delivered_no_content 的 ``unhandled_for`` 先例），
        否则每轮 full_scan（30 分钟周期）重复追加 major 告警。配套地，本
        告警以 ``spec=None`` 哨兵落盘（daemon 级清单型告警无单一归属 spec，
        清单完整保留在 description/evidence）——``unhandled_for(None, …)``
        预查只匹配 spec=None 记录，写非 None spec 会使幂等防重永不生效
        （对齐 admin_monitor restart_failed 先例）。

        ``anchored``（216a09577e1a）：skipped 中框架锚定豁免条目的子清单，
        渲染措辞与非法名条目区分；仅锚定豁免（无清退、无非法名）的轮次属
        在途正常形态，只 debug 留痕不升级人工（防告警噪音）。
        """
        anchored_set = set(anchored)
        # 需要人工介入的跳过条目 = 非法路径成分名（锚定豁免名排除在外）
        alertable_skipped = [s for s in skipped if s not in anchored_set]
        if not reclaimed and not alertable_skipped:
            if skipped:
                # 仅框架锚定豁免（在途实施中属正常形态）：debug 留痕即止，
                # 不发零清退 major 告警
                self._pm.logger.debug(
                    "pm_engine",
                    f"幽灵对账本轮无清退，仅 {len(skipped)} 条框架锚定豁免"
                    f"（在途正常形态，不升级）：{','.join(str(s) for s in skipped)}",
                )
            # 竞态空转（code-review item 9d66dd115abd）：检出后条目被并发
            # 写者全部移除，零副作用零清单——不发零条目 major 告警
            return False
        names = (
            [h["spec"] for h in reclaimed] + [str(s) for s in alertable_skipped]
        )
        spec_ref = names[0] if len(names) == 1 else ",".join(names)
        try:
            from core.admin_store import AdminStore

            store = AdminStore(self._pm.project_root, self._pm.logger)
            if store.unhandled_for(None, GHOST_RECLAIM_SIGNAL_TYPE) is not None:
                # 幂等命中：聚合告警在案待人工，不重复追加
                self._pm.logger.debug(
                    "pm_engine",
                    "幽灵条目聚合告警在案，本轮不重复告警"
                    f"（清退 {len(reclaimed)} 条 / 跳过 {len(alertable_skipped)} 条）",
                )
                return False
        except Exception as e:
            # 幂等预检失败不阻断告警写入（宁多一条不漏告警）
            self._pm.logger.warning(
                "pm_engine",
                f"幽灵清退告警幂等预检失败（继续写入）: {e}",
            )

        lines = []
        for hit in reclaimed:
            lines.append(
                f"- {hit['spec']}（status={hit.get('status')}）：已 remove_spec "
                f"清退；created={hit.get('created')}（距今 "
                f"{hit.get('age_minutes')} 分钟）；{hit.get('dir_evidence')}；"
                f"{hit.get('git_evidence')}"
            )
        for name in skipped:
            if name in anchored_set:
                lines.append(
                    f"- {name}：仍被框架锚定（implementer_run/branch 锚点或"
                    f"活跃 worktree 在场，在途实施中），本轮不清退（正常形态，"
                    f"无需人工处置）"
                )
            else:
                lines.append(
                    f"- {name}：spec 名含非法路径成分，保守跳过不清退，待人工处置"
                )
        detail = "\n".join(lines)
        anchored_note = (
            f"；另 {len(anchored_set)} 条框架锚定条目豁免清退（在途正常形态）"
            if anchored_set
            else ""
        )
        self._pm.logger.warning(
            "pm_engine",
            f"幽灵条目对账清退：{len(reclaimed)} 条清退 / "
            f"{len(alertable_skipped)} 条跳过待人工（{spec_ref}）",
        )
        # code-review item ff509339a250：spec 哨兵写 None——unhandled_for
        # (None, …) 幂等预查只匹配 spec=None 记录，写非 None 的 spec_ref
        # 会使防重永不生效、每轮 full_scan 重复追加（对齐 admin_monitor
        # restart_failed 先例）；清单完整进 description/evidence。
        self._pm._send_human_escalation_alert(
            spec_name=None,
            signal_type=GHOST_RECLAIM_SIGNAL_TYPE,
            severity="major",
            description=(
                f"幽灵条目对账清退：本轮结构性移除 {len(reclaimed)} 条「从未"
                f"立项」的裸注册条目（remove_spec + 台账留痕，替代逐条 "
                f"freeze→escalate），另有 {len(alertable_skipped)} 条非法名条目"
                f"保守跳过待人工{anchored_note}。清单：\n{detail}"
            ),
            evidence=(
                f"指纹=三条件 AND（spec_has_content False + git 全历史零提交"
                f"+ 注册超 {GHOST_ENTRY_FRESHNESS_MINUTES} 分钟，且不被框架"
                f"锚定）；台账=.fenix/{GHOST_RECLAIM_LEDGER_FILENAME}；明细："
                f"\n{detail}"
            ),
            recommended_action=(
                "核对清单证据确认清退无误后人工 handled 收口；如需保留某条目"
                "（如手工误判），物化 spec/changes/<name>/ 实质内容后正常重"
                "立项即可，本告警不自动闭环"
            ),
        )
        return True
