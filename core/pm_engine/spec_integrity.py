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
        # 四选一判定：proposal / design / tasks / specs/**/*.md 任一存在即满足
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

        Returns:
            True = 已拦（spec 因内容缺失被冻结，或已是 blocked 幂等）；
            False = 有内容 / IO 异常保守放行，调用方继续派发。
        """
        if spec_has_content(self._pm.project_root, spec_name):
            return False

        entry = self._pm.state_machine.read_one(spec_name) or {}
        if entry.get("status") == "blocked":
            # 已冻结（可能由本闸门或其它闸门触发）：不重复告警，但仍阻止重派
            return True

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
