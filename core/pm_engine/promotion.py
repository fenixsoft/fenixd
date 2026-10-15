"""core/pm_engine/promotion.py — 共享晋升函数（add-draft-promotion-gate D2）。

自动晋升链与人工放行通道（Dashboard API、CLI）共用此模块，确保晋升语义一致：
软化 → lint → 判定（返回 ok/violations，由调用方执行 transition + 派发）。
"""

from pathlib import Path
from typing import Optional


def promote_drafted(
    project_root: Path,
    spec_name: str,
    *,
    state_machine,
    logger,
    config: Optional[dict] = None,
) -> dict:
    """共享晋升函数：软化 + lint + 判定。

    Args:
        project_root: 项目根路径
        spec_name: SPEC 名称
        state_machine: StateMachine 实例（用于读取状态与写入 error）
        logger: 日志实例（需有 info/warning/error 方法）

    Returns:
        {"ok": True, "violations": [], "next_status": "ready"|"reviewing"} — 可晋升
        （调用方须按 next_status 决定 transition 目标再派发；取值由评审门禁判定：
        should_skip_review 判定跳过评审（gates.spec_review_mode / fast-track）→ "ready"，
        否则 → "reviewing"；config 为 None 时不做评审判定，恒 "ready"）
        {"ok": False, "violations": [...]} — lint 违规，STATE error 已写入
        {"ok": False, "reason": "..."} — 拒绝（不存在 / 非 drafted / 其它原因）
    """
    # 1. 检查 SPEC 是否存在且处于 drafted 状态
    entry = state_machine.read_one(spec_name)
    if entry is None:
        return {"ok": False, "reason": f"spec '{spec_name}' not found in STATE.md"}
    status = entry.get("status", "")
    if status != "drafted":
        return {"ok": False, "reason": f"spec '{spec_name}' status is '{status}', not 'drafted'"}

    # 2. 晋升前软化（soften_unsatisfiable_declarations + DisputeAuditStore 审计）
    #    软化编排异常降级 warning（fail-safe，不阻塞晋升流程）
    try:
        from core.deliverables import soften_unsatisfiable_declarations

        spec_dir = project_root / "spec" / "changes" / spec_name
        # tasks_path 绑定在分支外（spec_dir 拼接无需目录存在）：软化分支的
        # after 快照同样引用它，若仅在 is_dir() 块内绑定，目录缺失时会抛
        # UnboundLocalError 并被外层 except 吞成「软化编排异常」，归因失真
        tasks_path = spec_dir / "tasks.md"
        # 快照声明段（before）：供审计 diff
        before_text = ""
        if spec_dir.is_dir():
            if tasks_path.exists():
                try:
                    before_text = tasks_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    before_text = ""
        softened = soften_unsatisfiable_declarations(spec_dir, project_root)
        if softened:
            logger.info(
                "pm_engine",
                f"晋升前软化声明 '{spec_name}': "
                f"{[s['element'] for s in softened]}（kind → reference）",
            )
            # 快照软化后声明段（after）
            after_text = ""
            if tasks_path.exists():
                try:
                    after_text = tasks_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    after_text = ""
            try:
                from core.admin_store import DisputeAuditStore

                DisputeAuditStore(project_root, logger).append(
                    {
                        "spec": spec_name,
                        "trigger_run_id": "",
                        "judge_run_id": "",
                        "verdicts": [
                            {
                                "element": s["element"],
                                "verdict": "reference",
                                "reasoning": (f"promotion-soften: {s['reason']}"),
                            }
                            for s in softened
                        ],
                        "diff": {
                            "before": before_text,
                            "after": after_text,
                        },
                    }
                )
            except Exception as e:
                logger.warning(
                    "pm_engine",
                    f"晋升软化审计写盘失败 '{spec_name}'（非阻塞）: {e}",
                )
    except Exception as e:
        logger.warning(
            "pm_engine",
            f"晋升前软化编排异常 '{spec_name}'（降级走既有 lint 判定）: {e}",
        )

    # 3. 晋升 lint（deliverables 声明形态校验 + tasks.md 可解析性校验）
    violations = _lint_deliverable_declarations(project_root, spec_name, logger)
    tasks_violations = _lint_tasks_parseable(project_root, spec_name, logger)

    # 4. 违规判定：有违规 → 写 STATE error + 返回失败
    if violations or tasks_violations:
        msgs = []
        if violations:
            msgs.append("Deliverables 声明 lint 未通过：" + "；".join(violations))
        if tasks_violations:
            msgs.append("tasks.md 可解析性 lint 未通过：" + "；".join(tasks_violations))
        err = "；".join(msgs)
        logger.error(
            "pm_engine",
            f"Promotion lint failed '{spec_name}': {err}",
        )
        # 写前冻结复查（code-review item 29de1ddc2fbc，对齐 dispatch/rollback
        # ._rollback_frozen_recheck 先例）：入口 status 快照（本函数第 1 步）到
        # 此处隔着软化编排与两项 lint 的文件 I/O，窗口内 spec 可能已被并发
        # 冻结——frozen 条目的 update_spec 只剥 status 键，本 error 直写照常
        # 生效，会覆盖内嵌「原状态 X」的冻结 error，人工解冻经 parse_orig_status
        # 无法还原。发现冻结即放弃本次 error 写（violations 照常返回，由调用方
        # 呈现），冻结现场保留待人工解冻后重新晋升。
        from core.state_machine import FROZEN_FIELD

        if (state_machine.read_one(spec_name) or {}).get(FROZEN_FIELD):
            logger.warning(
                "pm_engine",
                f"Promotion lint error write abandoned '{spec_name}': "
                "写盘前复查发现已冻结——放弃 error 直写，冻结现场保留待人工解冻",
            )
            return {"ok": False, "violations": violations + tasks_violations}
        state_machine.update_spec(spec_name, {"error": err})
        return {"ok": False, "violations": violations + tasks_violations}

    # 5. 全部通过，返回可晋升，并确定 next_status
    next_status = "ready"
    if config is not None:
        # 跳过评审判定
        skip = should_skip_review(project_root, spec_name, config, logger)
        if not skip:
            next_status = "reviewing"
    return {"ok": True, "violations": [], "next_status": next_status}


def _lint(project_root: Path, spec_name: str, logger, fn_name: str, label: str) -> list:
    """晋升 lint 公共执行器（fail-open）。

    fn_name 为 core.deliverables 上的 lint 函数名（函数内延迟导入防循环导入）；
    import 与执行任一环节异常（循环导入/半部署损坏/读取失败）一律降级为
    warning + 空列表（非阻塞放行），不让异常沿 promote_drafted 传播中断晋升链。
    """
    spec_dir = project_root / "spec" / "changes" / spec_name
    if not spec_dir.is_dir():
        return []
    try:
        from core import deliverables

        return getattr(deliverables, fn_name)(spec_dir, project_root)
    except Exception as e:
        logger.warning(
            "pm_engine",
            f"{label} lint 异常 '{spec_name}'（非阻塞放行）: {e}",
        )
        return []


def _lint_deliverable_declarations(project_root: Path, spec_name: str, logger) -> list:
    """Deliverables 声明形态 lint（晋升前拦截，fail-open）。"""
    return _lint(project_root, spec_name, logger, "lint_declared", "Deliverables")


def _lint_tasks_parseable(project_root: Path, spec_name: str, logger) -> list:
    """tasks.md 可解析性 lint（晋升前拦截，fail-open，task-track D2）。"""
    return _lint(
        project_root, spec_name, logger, "lint_tasks_parseable", "tasks.md 可解析性"
    )


def should_skip_review(project_root: Path, spec_name: str, config: dict, logger) -> bool:
    """评审跳过判定：四项全部命中才跳过。

    1. `.spec.yaml` 的 `mode` 为 `fast-track`
    2. `specs/` 下的能力目录数 ≤ 1
    3. `tasks.md` 的 Deliverables 声明段条目数 ≤ 3
       （例外：空声明段（0 条）按不满足处理，仍走评审）
    4. SPEC 名 MUST NOT 以 `evo-` 开头

    字段缺失时保守取「不跳过」。gates.spec_review_mode: never 时恒返回跳过。
    """
    # gates.spec_review_mode: never 时直接跳过
    try:
        from core.config import ConfigLoader

        mode = ConfigLoader.get_spec_review_mode(config)
    except Exception as e:
        # ConfigLoader 导入/判定异常：保守不跳过评审，不让异常沿
        # promote_drafted 传播中断晋升链
        logger.warning(
            "pm_engine",
            f"评审跳过判定异常 '{spec_name}'（保守不跳过评审）: {e}",
        )
        return False
    if mode == "never":
        return True

    spec_dir = project_root / "spec" / "changes" / spec_name
    if not spec_dir.is_dir():
        return False

    # 1. 检查 mode（走 core.spec_mode 单点，与引擎/派发/守卫读 mode 口径统一；
    #    文件缺失/无 mode 字段/值非法/解析失败一律回退 "full"，即保守不跳过评审）
    try:
        from core.spec_mode import read_spec_mode

        if read_spec_mode(project_root, spec_name) != "fast-track":
            return False
    except Exception as e:
        # .spec.yaml 读取异常：保守不跳过评审，不让异常沿 promote_drafted
        # 传播中断晋升链
        logger.warning(
            "pm_engine",
            f".spec.yaml 读取/解析异常 '{spec_name}'（保守不跳过评审）: {e}",
        )
        return False

    # 2. 能力目录数 ≤ 1
    specs_dir = spec_dir / "specs"
    if specs_dir.is_dir():
        try:
            cap_dirs = [d for d in specs_dir.iterdir() if d.is_dir()]
        except OSError:
            # is_dir 判定后目录被并发删除（归档/清理）：保守不跳过评审，
            # 不让异常沿 promote_drafted 传播中断晋升链
            logger.warning(
                "pm_engine",
                f"specs 目录枚举竞态（被并发删除？）'{spec_name}'（保守不跳过评审）",
            )
            return False
        if len(cap_dirs) > 1:
            return False
    else:
        # 没有 specs 目录，视为 0 个能力目录，满足条件
        pass

    # 3. Deliverables 声明段条目数 ≤ 3（复用 core.deliverables 权威解析：
    #    声明段定位/条目计数单点在 extract_declared_entries，勿维护第二份
    #    围栏解析——按全文首个 yaml 围栏计数会与 `## Deliverables` 段定位
    #    口径漂移：前部其他围栏恰含 ≤3 条 `- path:` 而真实声明段 >3 条时，
    #    会误判满足本条件跳过评审）
    try:
        from core.deliverables import extract_declared_entries

        entries = extract_declared_entries(spec_dir)
    except Exception as e:
        # 解析异常（异常形态 tasks.md）：保守不跳过评审，不让异常沿
        # promote_drafted 传播中断晋升链
        logger.warning(
            "pm_engine",
            f"Deliverables 声明段解析异常 '{spec_name}'（保守不跳过评审）: {e}",
        )
        return False
    if not entries:
        return False
    if len(entries) > 3:
        return False

    # 4. SPEC 名不以 evo- 开头
    if spec_name.startswith("evo-"):
        return False

    return True
