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
from pathlib import Path

# 可传播到 fenixd 已挂载 handler 的结构化日志器（fix-robustness-edge-cases 3.1：
# 收敛旁路裸 getLogger("pm_engine")，保证 WARNING 落入 fenixd.log）
_logger = logging.getLogger("fenixd.pm_engine.spec_integrity")

# 终态口径（alert-noise-governance 1.1）：与 alert_lifecycle.TERMINAL_SPEC_STATUSES
# （done/pushed）同口径，另含 spec.md 场景文本使用的 archived 拼写（状态机
# 当前不产出该值，纳入仅为向前兼容，避免规格语言与实现口径漂移）。
_TERMINAL_SPEC_STATUSES = ("done", "pushed", "archived")

# 「已交付未落盘」独立信号（alert-noise-governance 1.2）：目录无认可内容但
# 存在 verification-report.md 时，替代 spec_content_missing 的 signal_type。
# 闭环条件映射见 core/alert_lifecycle.py（spec_delivered_adjudicated）。
SPEC_DELIVERED_NO_CONTENT_SIGNAL = "spec_delivered_no_content"

# 「已交付未落盘」判定凭据：验证链落盘的验证报告（core/verify_report.py
# 写入 spec/changes/<spec>/verification-report.md）。它是验证产物而非 spec
# 起草内容，故只作分类凭据、不进 spec_has_content 认可名单（见其注释）。
_DELIVERED_REPORT_FILENAME = "verification-report.md"


def spec_has_content(project_root, spec_name: str) -> bool:
    """判定 spec 目录是否含实质内容（纯函数，design D2）。

    Args:
        project_root: 项目根（Path 或可转 Path 的路径）。
        spec_name: spec 名，对应 ``spec/changes/<spec_name>/`` 目录。

    Returns:
        True = 有实质内容（或读目录异常保守放行）；
        False = 目录不存在 / 目录为空 / 无常驻 spec 内容文件。
    """
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
            if next(specs_dir.rglob("*.md"), None) is not None:
                return True
        return False
    except OSError:
        # 读目录异常保守放行：权限/临时不可达下宁可放行让预算闸门兜底
        _logger.warning(
            "读取 spec 目录失败（保守放行）: %s",
            spec_dir,
        )
        return True


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

        entry = self._pm.state_machine.read_one(spec_name) or {}
        status = entry.get("status")
        if status == "blocked":
            # 已冻结（可能由本闸门或其它闸门触发）：不重复告警，但仍阻止重派
            return True

        if status in _TERMINAL_SPEC_STATUSES:
            # 终态豁免（alert-noise-governance 1.1，design D1）：已交付/归档
            # spec 不因目录内容缺失被反向冻结、不产 spec_content_missing——
            # 外部 STATE 重置把已交付 spec 打回后按「空 spec」冻结，处置方向
            # 与事实相反（c-sched-set 实证：实现已合并、验证 25/25 通过仍被
            # 冻结挂 major 告警，gate-delivered-spec-exemption 登记链）。
            # **终态豁免不等于放行派发**：本分支只免「冻结 + 告警」处置，不
            # 新增任何派发放行语义——「已交付未落盘」目录的派发拦截由下方分
            # 类分支与 spec_has_content 判据承担（返回 True）；终态 spec 出现
            # 在派发队列本身属异常，由派发层状态机语义管辖（非法 transition
            # 被拒），不由本闸门越权代管。
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
