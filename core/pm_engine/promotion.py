"""core/pm_engine/promotion.py — 共享晋升函数（add-draft-promotion-gate D2）。

自动晋升链与人工放行通道（Dashboard API、CLI）共用此模块，确保晋升语义一致：
软化 → lint → 判定（返回 ok/violations，由调用方执行 transition + 派发）。
"""

from pathlib import Path
from typing import Any, Optional


def promote_drafted(
    project_root: Path,
    spec_name: str,
    *,
    state_machine,
    logger,
    config: dict = None,
) -> dict:
    """共享晋升函数：软化 + lint + 判定。

    Args:
        project_root: 项目根路径
        spec_name: SPEC 名称
        state_machine: StateMachine 实例（用于读取状态与写入 error）
        logger: 日志实例（需有 info/warning/error 方法）

    Returns:
        {"ok": True, "violations": []} — 可晋升（调用方 transition + 派发）
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


def _lint_deliverable_declarations(project_root: Path, spec_name: str, logger) -> list:
    """Deliverables 声明形态 lint（晋升前拦截，fail-open）。"""
    from core.deliverables import lint_declared

    spec_dir = project_root / "spec" / "changes" / spec_name
    if not spec_dir.is_dir():
        return []
    try:
        return lint_declared(spec_dir, project_root)
    except Exception as e:
        logger.warning(
            "pm_engine",
            f"Deliverables lint 异常 '{spec_name}'（非阻塞放行）: {e}",
        )
        return []


def _lint_tasks_parseable(project_root: Path, spec_name: str, logger) -> list:
    """tasks.md 可解析性 lint（晋升前拦截，fail-open，task-track D2）。"""
    from core.deliverables import lint_tasks_parseable

    spec_dir = project_root / "spec" / "changes" / spec_name
    if not spec_dir.is_dir():
        return []
    try:
        return lint_tasks_parseable(spec_dir, project_root)
    except Exception as e:
        logger.warning(
            "pm_engine",
            f"tasks.md 可解析性 lint 异常 '{spec_name}'（非阻塞放行）: {e}",
        )
        return []


def should_skip_review(project_root: Path, spec_name: str, config: dict, logger) -> bool:
    """评审跳过判定：四项全部命中才跳过。

    1. `.spec.yaml` 的 `mode` 为 `fast-track`
    2. `specs/` 下的能力目录数 ≤ 1
    3. `tasks.md` 的 Deliverables 声明段条目数 ≤ 3
    4. SPEC 名 MUST NOT 以 `evo-` 开头

    字段缺失时保守取「不跳过」。gates.spec_review_mode: never 时恒返回跳过。
    """
    from core.config import ConfigLoader

    # gates.spec_review_mode: never 时直接跳过
    mode = ConfigLoader.get_spec_review_mode(config)
    if mode == "never":
        return True

    spec_dir = project_root / "spec" / "changes" / spec_name
    if not spec_dir.is_dir():
        return False

    # 1. 检查 mode
    spec_yaml = spec_dir / ".spec.yaml"
    if not spec_yaml.exists():
        return False
    try:
        import yaml

        with spec_yaml.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return False
    if data.get("mode") != "fast-track":
        return False

    # 2. 能力目录数 ≤ 1
    specs_dir = spec_dir / "specs"
    if specs_dir.is_dir():
        cap_dirs = [d for d in specs_dir.iterdir() if d.is_dir()]
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
    from core.deliverables import extract_declared_entries

    entries = extract_declared_entries(spec_dir)
    if not entries:
        return False
    if len(entries) > 3:
        return False

    # 4. SPEC 名不以 evo- 开头
    if spec_name.startswith("evo-"):
        return False

    return True
