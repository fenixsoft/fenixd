"""core.pm_engine.verification.scenario_gate — 场景冻结/交互契约/静态检查（refactor-verification-module D2）。

从 VerificationPipeline 摘出的场景冻结（_apply_scenario_freeze）、交互契约
（_apply_interaction_contract）、冻结场景读取、场景变更报告段渲染、契约缺失
标记、场景静态检查与契约静态检查。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。

实例缓存态 `_last_scenario_diff` / `_last_interaction_contract` /
`_last_freeze_rejected*` 写入 pipeline 实例属性（engine.py 经
`self._verification._last_scenario_diff` 读取，路径不变）。
"""

import json
import re
import time
from pathlib import Path
from typing import Optional


def _apply_scenario_freeze(pipeline, spec_name: str) -> dict:
    """应用场景集冻结：planner 产出 vs 持久化集 diff，写回 scenarios.json。

    design D3：确定性、纯 Python，planner 无法通过输出文本绕过。
    在场景执行前调用（_run_three_stage_verification 阶段1 之后）。

    写端 schema 门（fix-frozen-scenario-orphan-reservoir D1/D2/D3）：
    - 收编写回 / 补齐写回 test_scenarios.json 前过 ``validate_scenario_dicts``
      同源校验（与读端 load_scenarios 同源），坏条目剔除留痕（id 清单）、
      不整批拒绝；剔除数超本轮 20% 时 ERROR 升级（Task 2.4）。
    - ``_scenarios_full.json`` 备份仅当 planner 产出全部合法时更新
      （备份价值在「可恢复」，存毒即失去价值）；含非法条目时保留旧备份
      + WARNING 留痕。
    - 无理由缺场景且备份缺定义 → 改弃场景（D3）：登记「定义不可恢复」
      剔除清单，不再写 ``{"id","description"}`` 非法占位，验证以剩余
      场景继续；备份有完整定义时维持既有补回行为（Task 3.2）。

    写前客户端预校验（evo-planner-scenario-schema-alignment 3.1-3.10）：
    - planner 产出进入阶段2 前逐条过与写端一致的校验器
      （``validate_scenario_dicts``，与读端同源且含旧 schema 迁移），
      非法条目剔除留痕（场景 id + 缺失字段），合法部分照常进入执行，
      MUST NOT 等整批落盘后整批剔除（09-13 两批 100% 剔除 → 阶段2
      整轮失败退回的既有路径）。
    - 3.3 移除声明豁免：携带 ``remove_reason`` 的声明条目不过滤
      （纯移除声明过不了 validate_scenario_dicts——缺 navigate 步骤等），
      令 diff 仍看到移除声明、仅对「实际写入集」过滤——否则理由丢失、
      planner 显式移除被静默反转为保留。
    - 3.2 主路径写回（MUST）：过滤得合法集后，于主路径把合法子集整体
      重写回 test_scenarios.json（事故实证条件——第 1 轮 / persisted 为空 /
      无理由缺失 0——永不进补齐分支，若只把写回挂补齐分支，非法条目仍留
      在文件、阶段2 仍旧整轮失败）；与补齐分支写回互斥（补齐分支已写即
      不再写），两处写回内容均为过滤后集合。
    - 3.5/3.8 空集显式兜底：过滤后无合法场景 → 不写空 test_scenarios.json、
      不 save_scenario_set（防止持久化集被写成空集——load_scenario_set 对
      ``scenarios: []`` 返回非 None、下一轮 diff 从首轮全量口径退化增量
      口径），以结构化返回值 ``{'aborted': 'no_valid_scenarios', ...}``
      承载信号，由调用点消费（阶段1 主路径退回 plan / 重排预算耗尽显式
      结束；judge 重入路径拒绝重入）——MUST NOT 依赖加载报错通道
      （写回合法子集后该报错不再触发，0 场景报告会被洗白门 fail-open
      放行判 verified）。
    - 3.9 剔除比例口径：超本轮 20% 的 ERROR 升级以写回前最终合法集为
      基准统计（两遍剔除——过滤 pass 与补齐 pass——合并）。
    - 3.10 剔除留痕：剔除条目 id 与 covers 存实例属性，紧随其后的
      ``_apply_interaction_contract`` 据此把「条目非法剔除」与「设计漏项」
      缺口区分开，避免「重排-剔除」循环。

    Returns:
        dict：{'diff': <DiffResult>, 'path': <写入路径>}，便于报告渲染复用；
        空集显式兜底时返回 {'aborted': 'no_valid_scenarios', 'rejected':
        [<逐条剔除描述>], 'total': <原始总数>, 'path': <场景文件路径>}。
    """
    from core.verify_scenarios import (
        load_scenario_set,
        diff_planner_output,
        save_scenario_set,
    )
    from core.verify_engine.scenarios import (
        validate_scenario_dicts,
        prepare_scenarios_for_write,
    )

    verify_dir = pipeline._context.project_root / ".fenix" / "verify-progress" / spec_name
    scenarios_path = verify_dir / "test_scenarios.json"
    if not scenarios_path.exists():
        return {}
    try:
        planner_scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(planner_scenarios, list):
        return {}

    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    current_round = pipeline._current_verify_round(spec_name)

    # ── 写前客户端预校验（3.1/3.3）：逐条过与写端一致的校验器 ──
    # 过滤出「实际写入集」（valid_planner）与「diff 输入集」（diff_input ＝
    # 合法集 + 携带 remove_reason 的移除声明，3.3 移除声明豁免）。
    valid_planner: list = []
    rejected: list[str] = []
    rejected_ids: list[str] = []
    diff_input: list = []
    for idx, item in enumerate(planner_scenarios):
        if not isinstance(item, dict):
            rejected.append(f"[{idx}]非对象({type(item).__name__})")
            continue
        item_id = item.get("id") or f"[{idx}]"
        if isinstance(item.get("remove_reason"), str) and item["remove_reason"]:
            # 3.3：纯移除声明条目保留进 diff 输入（移除理由照常生效），
            # 不参与写回（其形态本就不是可执行场景）。
            diff_input.append(item)
            continue
        errs = validate_scenario_dicts([item])
        if errs:
            rejected.append(f"{item_id}（{'；'.join(errs[:2])}）")
            rejected_ids.append(str(item_id))
            continue
        valid_planner.append(item)
        diff_input.append(item)

    # 3.10：剔除条目 id 与 covers 留痕（交互契约消费——被剔除场景覆盖的
    # 候选不属「设计漏项」缺口，避免「重排-剔除」循环）。
    pipeline._last_freeze_rejected = list(rejected_ids)
    rejected_covers: set = set()
    rejected_set = set(rejected_ids)
    for item in planner_scenarios:
        if not isinstance(item, dict):
            continue
        if item.get("id") in rejected_set:
            covers = item.get("covers")
            if isinstance(covers, list):
                rejected_covers.update(str(c) for c in covers if c)
    pipeline._last_freeze_rejected_covers = rejected_covers

    # ── 空集显式兜底（3.5/3.8）：全部条目非法 → 不写空文件、不持久化 ──
    # 写回合法子集后「全部非法」不再触发阶段2 load_scenarios 报错（既有
    # 退回路径依赖的正是该报错），必须在此显式判定；0 场景经 engine.run([])
    # 产出无 env_error 的全绿报告、会被洗白门 fail-open 放行判 verified，
    # 故空集 MUST NOT 以 0 场景继续进入阶段2。空集判定先于 save_scenario_set
    # （3.8）：持久化集保持不变，下一轮 diff 维持首轮全量口径。
    if not valid_planner:
        if rejected:
            reject_note = "、".join(rejected)
            pipeline._context.logger.error(
                "pm_engine",
                f"场景写前预校验整批拒绝 '{spec_name}'（{len(rejected)}/"
                f"{len(planner_scenarios)} 条全部非法），无合法场景可执行 "
                f"— 不写空文件/不持久化，退回 plan 重排: {reject_note}",
            )
        return {
            "aborted": "no_valid_scenarios",
            "rejected": rejected,
            "total": len(planner_scenarios),
            "path": str(scenarios_path),
        }

    # ── 剔除留痕（第一遍，3.4 既有语义：超本轮 20% ERROR 升级）──
    if rejected:
        reject_note = "、".join(rejected)
        total = len(planner_scenarios) or 1
        ratio = len(rejected) / total
        log_fn = pipeline._context.logger.error if ratio > 0.2 else pipeline._context.logger.warning
        log_fn(
            "pm_engine",
            f"场景写前预校验剔除 {len(rejected)}/{len(planner_scenarios)} "
            f"条非法条目（{'超本轮20%' if ratio > 0.2 else '未超20%'}），"
            f"合法部分照常执行: {reject_note}",
        )

    diff = diff_planner_output(
        pipeline._context.project_root, spec_name, entry, diff_input, current_round
    )
    if rejected:
        reject_note = "、".join(rejected)
        diff.change_lines.append(
            f"- 写前预校验剔除 {len(rejected)} 条非法条目（未落盘）：{reject_note}"
        )

    # 写回 scenarios.json（原子写；首轮写入 / 合并追加 / 补齐后稳定集）
    path = save_scenario_set(pipeline._context.project_root, diff.scenario_set)
    # 全量场景定义备份（_scenarios_full.json）：供无理由缺场景时按持久化集
    # 补齐 test_scenarios.json 的原始定义（design D2：不丢回归面）。
    # 仅当本轮未删减既有场景时更新备份（保留最全的历史定义）。
    # D2 特例：备份仅当 planner 产出全部合法时更新——存毒即失去可恢复价值，
    # 含非法条目时保留旧备份并 WARNING 留痕。
    # D3 交互：当存在无理由缺场景（unreasoned_missing）时，旧备份是补回
    # 所需的历史定义源——此时 MUST NOT 覆盖（否则 reconcile 无法取回定义，
    # 缺定义场景被误判为不可恢复）。仅当 diff.ok（无无理由缺失）时更新。
    if not diff.removed and not diff.unreasoned_missing:
        if rejected:
            pipeline._context.logger.warning(
                "pm_engine",
                f"场景备份未更新 '{spec_name}'：planner 产出含 "
                f"{len(rejected)} 条非法条目（_scenarios_full.json 存毒即"
                f"失去可恢复价值，保留旧备份）",
            )
        else:
            full_backup = verify_dir / "_scenarios_full.json"
            try:
                # frozen-scenario-schema-migration 2.1：写端恒定写入
                # schema_version 标记（旧字段先迁移再落盘，读侧直通）
                # tmp+replace 原子写（与本函数 test_scenarios.json 写回同款）：
                # 裸写中途被 SIGKILL/断电会留下截断备份，下轮无理由缺场景补齐
                # 读备份失败（backup_map 置空），场景被判「定义不可恢复」剔除。
                tmp = full_backup.with_name(full_backup.name + ".tmp")
                tmp.write_text(
                    json.dumps(
                        prepare_scenarios_for_write(valid_planner),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                tmp.replace(full_backup)
            except OSError as e:
                # 3.6：写失败不得零痕迹——备份是后续无理由缺场景补齐的唯一
                # 恢复源，写失败后下轮补齐将因 backup_map 为空把场景判
                # 「定义不可恢复」剔除（静默缩小回归面），ERROR 留痕可归因。
                pipeline._context.logger.error(
                    "pm_engine",
                    f"全量场景备份写回失败 '{spec_name}'（_scenarios_full.json "
                    f"未更新，缺场景补齐将失去恢复源）: {e}",
                )
    pipeline._context.logger.info(
        "pm_engine",
        f"场景集冻结 '{spec_name}'（第 {current_round} 轮）：稳定集 "
        f"{len(diff.scenario_set.scenarios)} 个，新增 {len(diff.added)}，"
        f"有理由移除 {len(diff.removed)}，无理由缺失 {len(diff.unreasoned_missing)}",
    )

    # ── 写回 test_scenarios.json 的合法子集（3.2/3.6/3.9）──
    # 两处写点互斥 3.2：补齐分支（无理由缺场景时以持久化集补齐后写回）与
    # 主路径写回；两处内容均为过滤后集合。第二遍剔除（write_rejected，补齐
    # pass 对备份取回条目再剔一批）与第一遍合并统计 3.9。
    write_rejected: list[str] = []
    final_valid: list = []
    if not diff.ok and diff.unreasoned_missing:
        # 无理由缺场景 → 以持久化集补齐 test_scenarios.json（不中断验证，
        # design D2）：planner 实际执行的场景文件必须含全部既有场景，否则
        # 回归面丢失。优先从上一轮全量备份 _scenarios_full.json 取回被丢弃
        # 场景的原始定义。
        missing_ids = {e.id for e in diff.unreasoned_missing}
        reconciled = [
            s
            for s in valid_planner
            if isinstance(s, dict) and s.get("id") and s.get("id") not in missing_ids
        ]
        backup = verify_dir / "_scenarios_full.json"
        backup_map = {}
        if backup.exists():
            try:
                for s in json.loads(backup.read_text(encoding="utf-8")):
                    if isinstance(s, dict) and s.get("id"):
                        backup_map[s["id"]] = s
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                backup_map = {}
        # D3：备份缺定义 → 改弃场景（不再写 {"id","description"} 占位）。
        # 备份取回的条目可能来自旧备份（未经写端门），统一过下方
        # 收编写回 schema 门剔除坏条目；备份缺定义的条目登记「定义不可恢复」
        # 从本轮验证集剔除（宁少验一个，不写必败文件）。
        unrecoverable: list[str] = []
        for mid in missing_ids:
            if mid in backup_map:
                reconciled.append(backup_map[mid])
            else:
                unrecoverable.append(mid)
        if unrecoverable:
            pipeline._context.logger.error(
                "pm_engine",
                f"无理由缺失且备份缺定义的场景定义不可恢复，从本轮验证集"
                f"剔除（宁少验一个，不写必败文件）: {'、'.join(unrecoverable)}",
            )
            diff.change_lines.append(
                f"- 无理由缺失且备份缺定义的场景 {len(unrecoverable)} 个"
                f"定义不可恢复，已剔除：{'、'.join(unrecoverable)}"
            )
        # ── 收编写回 schema 门（D1/D2 / 3.1 同校验收敛）──
        # 备份取回条目与合法 planner 产出再次整体过结构校验：坏条目剔除留痕，
        # 合法部分照常落盘，不整批拒绝。
        write_valid: list = []
        for idx, item in enumerate(reconciled):
            if not isinstance(item, dict):
                write_rejected.append(f"[{idx}]非对象({type(item).__name__})")
                continue
            item_id = item.get("id") or f"[{idx}]"
            errs = validate_scenario_dicts([item])
            if errs:
                write_rejected.append(f"{item_id}（{'；'.join(errs[:2])}）")
                continue
            write_valid.append(item)
        if write_rejected:
            pipeline._context.logger.warning(
                "pm_engine",
                f"补齐写回剔除 {len(write_rejected)} 条非法条目（未落盘）: "
                f"{'、'.join(write_rejected)}",
            )
            diff.change_lines.append(
                f"- 补齐写回剔除 {len(write_rejected)} 条非法条目（未落盘）："
                f"{'、'.join(write_rejected)}"
            )
        try:
            # frozen-scenario-schema-migration 2.1：补齐写回同样恒定写入
            # schema_version（备份取回条目可能为旧 schema，先迁移再落盘）
            # tmp+replace 原子写（与本文件 _render_scenario_change_section_to_report
            # 同款）：裸写中途被 SIGKILL/断电会留下截断 JSON，下一轮
            # _load_frozen_scenarios 会误判 corrupt，触发一轮人工裁决停摆。
            tmp = scenarios_path.with_name(scenarios_path.name + ".tmp")
            tmp.write_text(
                json.dumps(
                    prepare_scenarios_for_write(write_valid),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(scenarios_path)
        except OSError as e:
            # 3.6：写回相关异常须 ERROR 留痕（外层 except 仅记 WARNING）
            pipeline._context.logger.error(
                "pm_engine",
                f"补齐场景写回失败 '{spec_name}'（spec 可能仍以未过滤文件" f"进入阶段2）: {e}",
            )
        final_valid = write_valid
    else:
        # ── 3.2 主路径写回（MUST，否则本修复对本次事故空转）──
        # 事故实证条件（第 1 轮 / persisted 为空 / 无理由缺失 0）永不进入
        # 上方补齐分支（verification.py:1296），而补齐分支是既有唯一写点；
        # 若只把写回挂补齐分支，非法条目仍留在 planner 写的文件、阶段2
        # 仍旧整轮失败。故在主路径写回过滤后合法子集，覆盖首轮/无缺失轮。
        try:
            # tmp+replace 原子写（与本文件 _render_scenario_change_section_to_report
            # 同款）：裸写中途被 SIGKILL/断电会留下截断 JSON，下一轮
            # _load_frozen_scenarios 会误判 corrupt，触发一轮人工裁决停摆。
            tmp = scenarios_path.with_name(scenarios_path.name + ".tmp")
            tmp.write_text(
                json.dumps(
                    prepare_scenarios_for_write(valid_planner),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(scenarios_path)
        except OSError as e:
            # 3.6：写回成为主路径，异常以 ERROR 留痕（不得只留 WARNING 旁证）
            pipeline._context.logger.error(
                "pm_engine",
                f"场景合法子集主路径写回失败 '{spec_name}'（spec 将仍以 "
                f"planner 原文件进入阶段2，非法条目可能致整批失败）: {e}",
            )
        final_valid = valid_planner

    # ── 3.9 剔除比例合并统计（以写回前最终合法集为基准）──
    # 既有实现只统计第一遍 rejected（过滤 pass）；补齐 pass 的剔除
    # （write_rejected，含从备份取回的既有场景）现仅 WARNING、无比例升级，
    # 会静默缩小回归面。两遍合并后统一按「写回前最终合法集」基准升级。
    if rejected or write_rejected:
        total_rejected = len(rejected) + len(write_rejected)
        base = len(final_valid) or 1  # 写回前最终合法集为基准（3.9 口径）
        ratio = total_rejected / base
        if ratio > 0.2:
            pipeline._context.logger.error(
                "pm_engine",
                f"场景剔除合计超本轮 20%（{total_rejected} 条剔除 / 写回前"
                f"最终合法集 {len(final_valid)} 条，比例 {ratio:.0%}）"
                f"'{spec_name}' — 可见性兜底升级（非退回触发器）",
            )
            diff.change_lines.append(
                f"- 场景剔除合计 {total_rejected} 条（过滤 pass "
                f"{len(rejected)} + 补齐 pass {len(write_rejected)}），"
                f"超写回前最终合法集 20%"
            )

    pipeline._last_scenario_diff = diff  # 供报告渲染（2.3）读取
    return {"diff": diff, "path": str(path)}


def _apply_interaction_contract(pipeline, spec_name: str) -> dict:
    """场景执行前校验交互契约覆盖（design D1/D2）。

    页面类 SPEC 检出可交互候选时，校验场景集对每个候选的覆盖（``covers``
    登记 / 场景文本命中）或纯展示声明（``declared_display`` / SPEC 标注）。
    辅助治理：任何异常不阻断验证主流程。

    Returns:
        {"ok": True} 或 {"ok": False, "result": ContractResult,
        "feedback": <退回 plan 的反馈文本>, "uncovered": [元素标识]}
    """
    from core.interaction_contract import (
        validate_interaction_coverage,
        build_replan_feedback,
        load_planner_scenarios,
    )
    from core.verify_scenarios import load_scenario_set

    try:
        scenarios_path = (
            pipeline._context.project_root
            / ".fenix"
            / "verify-progress"
            / spec_name
            / "test_scenarios.json"
        )
        planner_scenarios = load_planner_scenarios(scenarios_path)
        if planner_scenarios is None:
            return {"ok": True, "skipped": True}
        persisted = load_scenario_set(pipeline._context.project_root, spec_name)
        result = validate_interaction_coverage(
            pipeline._context.project_root, spec_name, planner_scenarios, persisted
        )
        # evo-planner-scenario-schema-alignment 3.10：被 schema 预校验剔除的
        # 场景覆盖的候选不属「设计漏项」缺口——剔除已在该场景自身暴露结构
        # 问题并单独留痕（3.1 剔除 + 3.4/3.9 比例升级），覆盖校验将其从
        # uncovered 移除，避免「重排-剔除」循环（剔除改变文件 → 覆盖校验
        # 误判缺口 → 退回重排 → planner 再生成同类非法场景）。本去噪仅对
        # 覆盖登记（covers 字段）生效；未登记 covers 的文本命中式覆盖无法
        # 从剔除侧反推，按既有「设计漏项」判定（3.10 至少区分两类缺口）。
        rejected_covers = getattr(pipeline, "_last_freeze_rejected_covers", None) or set()
        if rejected_covers and not result.ok and result.uncovered:
            remaining = [k for k in result.uncovered if k not in rejected_covers]
            removed = [k for k in result.uncovered if k in rejected_covers]
            if removed:
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"交互契约覆盖校验 '{spec_name}'：{len(removed)} 个候选"
                    f"原由被 schema 预校验剔除的场景覆盖"
                    f"（{sorted(removed)}）— 归为「条目非法剔除」缺口，"
                    f"不计入设计漏项，不触发退回",
                )
                result.uncovered = remaining
                result.ok = not remaining
                result.change_lines.append(
                    f"- 元素 {'、'.join(sorted(removed))} 原由被 schema "
                    f"预校验剔除的场景覆盖（剔除已单独留痕），不属设计漏项"
                )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine", f"交互契约校验跳过 '{spec_name}'（不阻断）: {e}"
        )
        return {"ok": True, "skipped": True}

    pipeline._last_interaction_contract = result
    if result.ok:
        pipeline._context.logger.info(
            "pm_engine",
            f"交互契约覆盖校验通过 '{spec_name}'（候选 "
            f"{len(result.candidates)} 个，纯展示声明 {len(result.declared)} 个）",
        )
        return {"ok": True, "result": result}

    pipeline._context.logger.warning(
        "pm_engine",
        f"交互契约覆盖不完整 '{spec_name}': {result.uncovered}",
    )
    return {
        "ok": False,
        "result": result,
        "feedback": build_replan_feedback(result),
        "uncovered": list(result.uncovered),
    }


def _render_scenario_change_section_to_report(pipeline, spec_name: str) -> None:
    """把本轮场景集变更小节追加到 verification-report.md（spec 需求 2.3）。

    报告闸门（add-verify-report-gate）已保证文件存在；此处幂等追加，
    重复调用会因已存在「本轮场景集变更」标题而跳过。diff 来源优先级：
    ``_last_scenario_diff``（本轮冻结计算）> 重新读取 scenarios.json（首轮）。
    """
    diff = getattr(pipeline, "_last_scenario_diff", None)
    from core.verify_scenarios import (
        render_change_section,
        load_scenario_set,
        render_first_write_section,
    )

    if diff is None:
        persisted = load_scenario_set(pipeline._context.project_root, spec_name)
        if persisted is None:
            return
        section = render_first_write_section(persisted)
    else:
        section = render_change_section(diff)
    if not section.strip():
        return
    report_path = (
        Path(pipeline._context.project_root)
        / "spec"
        / "changes"
        / spec_name
        / "verification-report.md"
    )
    if not report_path.exists():
        return
    try:
        content = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if "## 本轮场景集变更" in content:  # 幂等：不重复追加
        return
    # add-verify-report-gate 要求不覆盖 mtime 语义仅针对「Agent 已写」文件；
    # 此处为框架追加小节，直接写回（Agent 漏写场景变更时由框架补）。
    # tmp+replace 原子写（与 verify_report.py 同款）：裸写中途崩溃会留下截断
    # 报告，截断残留仍携带本轮轮次指纹，会被报告闸门以 present 放行。
    try:
        tmp = report_path.with_name(report_path.name + ".tmp")
        tmp.write_text(content.rstrip("\n") + "\n" + section + "\n", encoding="utf-8")
        tmp.replace(report_path)
    except OSError as e:
        pipeline._context.logger.warning("pm_engine", f"场景集变更小节写回失败 '{spec_name}': {e}")


def _write_verify_contract_missing(
    pipeline, spec_name: str, note: str, evidence: str, recommended_action: str = ""
) -> None:
    """写 verify_contract_missing 信号呼叫 Administrator（契约相关 fail-fast 共用）。

    契约缺失/损坏/入口预检失败/轻量自证失败的统一出口（design D1/D2）：
    spawn 前确定性错误不等待失败计数与升级冷却，直接派发。失败记 warning
    不抛穿调用方（信号通道自身不可影响验证判定）。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(pipeline._context.project_root, pipeline._context.logger)
    try:
        store.append(
            {
                "kind": SIGNAL,
                "signal_type": "verify_contract_missing",
                "spec": spec_name,
                "severity": "major",
                "description": note,
                "evidence": evidence,
                "recommended_action": recommended_action
                or (
                    "Administrator 修正 .fenix/verify.yaml 验证契约："
                    "检查构建命令、serve 段入口/静态目录、端口注入；"
                    "修正后 git 提交 → spec 复位 ready 触发重验证"
                ),
            }
        )
    except Exception as e:
        pipeline._context.logger.error("pm_engine", f"verify_contract_missing 信号写入失败: {e}")


def _run_scenario_static_check(pipeline, spec_name: str) -> None:
    """场景静态缺陷扫描挂点（add-scenario-defect-triage-gate D3）。

    在场景集冻结完成后、阶段2 执行前调用（_run_three_stage_verification
    经门面转调）。findings 覆盖写 ``scenario_static_findings.json`` 供
    judge prompt 情报段注入——**只做情报不拦截执行**，任何异常记 WARNING
    不阻断验证（fail-open）。
    """
    from core.verify_engine.scenario_static_check import (
        scan_scenarios,
        write_findings,
    )

    scenarios_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "test_scenarios.json"
    )
    try:
        if not scenarios_path.exists():
            return
        data = json.loads(scenarios_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return
        serving_port = pipeline._serving_port_for_spec(spec_name)
        findings = scan_scenarios(data, serving_port=serving_port)
        write_findings(pipeline._context.project_root, spec_name, findings)
        if findings:
            from collections import Counter

            dist = dict(Counter(f.rule_id for f in findings))
            pipeline._context.logger.info(
                "pm_engine",
                f"场景静态扫描 '{spec_name}'（serving 端口 "
                f"{serving_port or '未知'}）检出 {len(findings)} 条情报: "
                f"{dist}",
            )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"场景静态扫描跳过 '{spec_name}'（fail-open，不阻断验证）: " f"{type(e).__name__}: {e}",
        )


def _run_contract_static_check(pipeline, spec_name: str) -> None:
    """契约只读一致性检查挂点（planner-contract-findings，design D4）。

    在 planner-plan 产物验收通过后（出题完成处）调用：对验证契约做只读
    一致性检查（入口存在性/与 start script 一致性/端口注入），findings
    覆盖写 ``contract_findings.json`` 供 admin 处置 prompt 注入。
    **只做情报不拦截出题**，任何异常记 WARNING 不阻断（fail-open）。
    """
    from core.verify_engine.scenario_static_check import (
        scan_contract,
        write_contract_findings,
    )

    try:
        findings = scan_contract(pipeline._context.project_root)
        write_contract_findings(pipeline._context.project_root, spec_name, findings)
        if findings:
            from collections import Counter

            dist = dict(Counter(f["rule_id"] for f in findings))
            pipeline._context.logger.info(
                "pm_engine",
                f"契约静态检查 '{spec_name}' 检出 {len(findings)} 条情报: " f"{dist}",
            )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"契约静态检查跳过 '{spec_name}'（fail-open，不阻断出题）: " f"{type(e).__name__}: {e}",
        )


def _load_frozen_scenarios(verify_dir: Path):
    """读取冻结场景集（scenario-reuse-on-reenter）。

    frozen-scenario-schema-migration：损坏判定携带字段级差异清单
    （load_scenarios ValueError 已含场景 id/下标/缺失字段），升级告警
    可凭差异精准修复，不再吞为笼统 corrupt。

    Returns:
        list[TestScenario]：冻结集有效（验收通过的原班场景）；
        None：无冻结文件（首次出题，走 planner 设计流程）；
        tuple ('corrupt', <差异清单文本>)：文件存在但验收失败（损坏/
        结构非法/为空）——场景一经冻结跨轮一致，变更须 admin 裁决，
        绝不静默重新出题。
    """
    from core.verify_engine.scenarios import load_scenarios

    path = verify_dir / "test_scenarios.json"
    if not path.is_file():
        return None
    try:
        scenarios = load_scenarios(path)
    except ValueError as e:
        return ("corrupt", str(e))
    except Exception as e:
        return ("corrupt", f"load_scenarios 非验收路径异常: {type(e).__name__}: {e}")
    if not scenarios:
        return ("corrupt", "冻结场景文件为空（无任何场景）")
    return scenarios
