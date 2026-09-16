"""core.pm_engine.verification.escalation — env 阻塞升级/告警/防御（refactor-verification-module D2）。

从 VerificationPipeline 摘出的 env 阻塞级升级通道、conclusive 处理、洗白门禁、
告警 streak 维护、陈旧三线告警、场景缺陷改道、judge env 声明、投机 bug 门禁。
纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# add-blocked-reverify-lane D3：env 阻塞轮次计数字段
from core.state_machine import ENV_BLOCK_ROUNDS_FIELD, FREEZE_ERROR_PREFIX

# judge-scenario-repair：judge 原地场景修复预算（上限重入轮数）
_SCENARIO_REPAIR_MAX_ROUNDS = 2


def _handle_env_blocked_inconclusive(pipeline, spec_name: str, report: dict) -> bool:
    """环境性失联门禁：全批 blocked-env → inconclusive → 保持 testing 重派新 attempt。

    inconclusive 判据（design D2）：summary.blocked_env > 0 且有效失败
    （failed + errors）为 0，即该轮原始失败全部为 blocked-env。

    处理：spec 回 implemented（verifier 派发门禁要求）→ 排队重验新 attempt；
    **不向 admin store 发 repeated_failures 信号**——本方法不产生 error 终态
    run 产物，repeated_failures 检测天然不累积（连续 inconclusive 不唤醒
    Administrator，对应 spec Scenario）。

    重验上限沿用 attempts=3（verify_engine.inconclusive_max_attempts 可调）：
    连续超限后停止自动重验、保持 implemented 并写 error 暴露，由
    admin_monitor stuck 检测唤起人工，不再无界自动重验。

    Returns:
        True 表示本轮已按 inconclusive 处理（调用方跳过 bug-found/verified
        判定）；False 表示无环境性失联，按既有判定继续。
    """
    summary = report.get("summary") or {}
    blocked_env = int(summary.get("blocked_env", 0) or 0)
    failed = int(summary.get("failed", 0) or 0)
    errors = int(summary.get("errors", 0) or 0)
    spec = pipeline._context.state_machine.read_one(spec_name) or {}
    if blocked_env <= 0 or (failed + errors) > 0:
        # add-verify-parallel-backoff / design D2：非 inconclusive 判定即
        # 健康轮（出现真实 verdict），复位降档并行度——存在才清，避免每轮
        # 无谓写盘（与 _inconclusive_attempts 同生命周期：链条断即复位）。
        if "_verify_parallel_override" in spec:
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "_verify_parallel_override": None,
                },
            )
        return False

    try:
        attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    max_attempts = int(
        pipeline._context.config_reader("verify_engine.inconclusive_max_attempts", 3) or 3
    )
    escalate_attempts = int(
        pipeline._context.config_reader("verify_engine.inconclusive_escalate_attempts", 4) or 4
    )

    # ── B7 升级通道（add-verdict-credibility-gate / design D6）──
    # 连续计数达到升级阈值（缺省 4）：向 admin store 写 kind=SIGNAL 记录，
    # 经 admin_monitor 摄取唤起 Administrator。三层既有检测口径
    # （repeated_failures / stuck / blocked_stuck）均实证错过该故障形态，
    # 不可依赖它们。写入后停止自动重验：计数不清零则 recovery（B6）保持
    # 跳过，人工处置是唯一出路——与「暂停自动重验」语义闭环。
    if attempts >= escalate_attempts:
        pipeline._write_inconclusive_loop_signal(spec_name, attempts, blocked_env, report)
        pipeline._context.logger.error(
            "pm_engine",
            f"'{spec_name}' 连续 {attempts} 轮验证全部 blocked-env，"
            f"已达升级阈值 {escalate_attempts}，SIGNAL 已写 admin store，"
            f"暂停自动重验等待人工处置",
        )
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "status": "implemented",
                "tester_run": None,
                "error": (
                    f"连续 {attempts} 轮验证全部环境性失联（blocked-env），"
                    f"已呼叫 Administrator 核查验证环境；"
                    f"人工处置后需清 _inconclusive_attempts 才能恢复自动重验"
                ),
                "_inconclusive_attempts": attempts,
                "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
            },
        )
        return True

    if attempts < max_attempts:
        pipeline._context.logger.warning(
            "pm_engine",
            f"'{spec_name}' 本轮 {blocked_env} 个失败场景全部为 blocked-env"
            f"（环境性失联），verdict=inconclusive，第 {attempts}/{max_attempts} 次重验",
        )
        updates = {
            "status": "implemented",
            "tester_run": None,
            "error": (
                f"环境性失联：{blocked_env} 个失败场景均 blocked-env，"
                f"第 {attempts}/{max_attempts} 次重验（inconclusive 不判 fail）"
            ),
            "_inconclusive_attempts": attempts,
        }
        # add-verify-parallel-backoff / design D1：连续 blocked-env 重验按
        # attempt 递减有效并行度——attempts≥2 起降档（配置值逐轮减半向下
        # 取整、下限 1），首轮不降档（白屏证据尚不存在，降档会冤枉健康
        # 环境）。下一轮 VerifyEngine 构造时读取覆盖 max_parallel。
        if attempts >= 2:
            base = int(pipeline._context.config_reader("verify_engine.max_parallel", 5) or 5)
            updates["_verify_parallel_override"] = max(1, base >> (attempts - 1))
        pipeline._context.state_machine.update_spec(spec_name, updates)
        pipeline._context.enqueue(spec_name, "verifier")
        return True

    # 连续 ≥max_attempts 轮全部环境性失联：停止自动重验，暴露错误等待人工。
    # 置 _dispatch_backoff_until 吸收同状态 update 触发的即时重派振荡。
    pipeline._context.logger.error(
        "pm_engine",
        f"'{spec_name}' 连续 {attempts} 轮验证全部 blocked-env，"
        f"疑为 mock/SSE 推送环境故障，暂停自动重验",
    )
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "status": "implemented",
            "tester_run": None,
            "error": (
                f"连续 {attempts} 轮验证全部环境性失联（blocked-env），"
                f"请人工检查 mock/SSE 推送环境；不产生 bug-found 信号"
            ),
            "_inconclusive_attempts": attempts,
            "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
        },
    )
    return True


def _env_whitewash_gate(pipeline, spec_name: str) -> bool:
    """verified 推进前的洗白不变量门禁（help-center 0/15 verified 事故防线）。

    verdict=verified 但 0 通过或存在 env 分类失败 → 阻断推进并升级：
    阻塞 spec → 自动呼叫 Administrator 处置环境 → 连续
    ENV_BLOCK_FREEZE_THRESHOLD 轮仍 env → 结构化冻结转人工。
    Returns: True=放行推进 verified；False=已升级处置（调用方直接 return）。
    """
    from core.verdict_check import load_report, whitewash_violations

    scenarios = []
    report = load_report(pipeline._context.project_root, spec_name)
    if report:
        scenarios = report.get("scenarios") or []
    if not scenarios:
        # report.json 缺位时回退结果文件场景（fast-track 等价路径）；
        # 读取异常一律视为无数据（门禁不制造新的失败模式）
        try:
            ft = pipeline._context.read_implementer_result(spec_name) or {}
            # fix-impl-tasks-completion-gate D6：partial 是「诚实申报未完成」
            # 的合法终态——其 verification 段是未完成形态，不得当作 verified
            # 洗白门禁的场景证据采信（partial 轮不会走到 verified 推进，此处
            # 为 fail-safe 兜底：按无数据处理，交既有闸门拦截）。
            if ft.get("status") == "partial":
                scenarios = []
            else:
                verification = ft.get("verification")
                if isinstance(verification, dict):
                    scenarios = verification.get("scenarios") or []
        except Exception:
            scenarios = []
    if not scenarios:
        return True  # 无场景数据不拦（保守放行，交既有闸门兜底）
    violations = whitewash_violations(scenarios, "verified")
    if not violations:
        return True
    pipeline._context.logger.warning(
        "pm_engine",
        f"verified 洗白门禁拦截 '{spec_name}': {'；'.join(violations)}",
    )
    pipeline._escalate_env_blocked(spec_name, violations)
    return False


def _escalate_env_blocked(
    pipeline, spec_name: str, violations: list, title: str = "验证环境阻塞"
) -> None:
    """阻塞升级通道：阻塞 spec → 自动呼叫 Administrator → 达阈值冻结转人工。

    help-center 事故语义（0/15 verified 被全量 env 豁免后推成 pushed）：
    env 失败绝不放行。首轮阻塞并自动呼叫 Administrator（依赖安装/服务
    重启/端口清理在其权限内），处置完成走既有重验证；连续 2 轮仍阻塞 →
    frozen 结构化冻结 + 人工升级告警——admin 权限也无法处理时唯一出口是
    人工介入。title 区分升级类别（验证环境阻塞 / 场景计划争议）。

    冻结转人工（fix-frozen-scenario-orphan-reservoir D5）：告警描述追加
    上轮 planner run 实际成本（tokens/费用/时长）作为「删除冻结集重新出题」
    的裁决参考。
    """
    try:
        spec = pipeline._context.state_machine.read_one(spec_name) or {}
        # ── evo-infra-failure-budget-exempt R2：env 阻塞属 infra ──
        # prepare/serve 失败（构建命令退出、端口不可达、自动启动失败）走
        # _escalate_env_blocked → blocked + admin（阈值 2 轮冻结转人工）；
        # infra 归类**只在其上补预算退款与 _verify_infra_rounds 记账**，
        # MUST 保持 env 通道 blocked 语义——「env 失败绝不放行」是既有刻意设计。
        # 归类挂钩点在 env 判定处（env 分支早退，归因入口不可达）。
        try:
            pipeline._record_infra_failure(
                spec_name,
                f"env blocked: {'; '.join(str(v) for v in (violations or [])[:3])}",
            )
        except Exception:
            pass  # 记账侧车，不阻断升级通道
        rounds = int(spec.get(ENV_BLOCK_ROUNDS_FIELD) or 0) + 1
        frozen = rounds >= 2  # 阈值：连续 2 轮阻塞 → 冻结转人工
        planner_cost = pipeline._last_planner_run_cost(spec_name) if frozen else ""
        cost_note = f"\n\n> 🪙 重新出题成本参考：{planner_cost}" if planner_cost else ""
        error_msg = (
            f"{FREEZE_ERROR_PREFIX}{title}连续 {rounds} 轮，"
            f"admin 处置未奏效，转人工 — {'；'.join(violations[:3])}"
            f"{cost_note}"
            if frozen
            else f"{title}（第 {rounds} 轮）：{'；'.join(violations[:3])}"
        )
        entry = {
            "status": "blocked",
            "error": error_msg,
            ENV_BLOCK_ROUNDS_FIELD: rounds,
        }
        if frozen:
            entry["frozen"] = True
        pipeline._context.state_machine.update_spec(spec_name, entry)
        if frozen:
            pipeline._context.logger.error(
                "pm_engine",
                f"'{spec_name}' {title}连续 {rounds} 轮，已冻结转人工",
            )
        else:
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' {title}第 {rounds} 轮，自动呼叫 Administrator 处置",
            )
        # 自动呼叫 Administrator：与 Dashboard 手动 invoke 同一信号通道
        # （.fenix/admin_invoke_request.json，daemon 主循环拾取派发）
        try:
            from core.dashboard.data import request_admin_invoke

            inv = request_admin_invoke(
                pipeline._context.project_root,
                spec_name,
                (
                    f"{title}自动升级（verified 洗白门禁/场景冻结复用）：{error_msg[:300]}。"
                    "请诊断并处置——处置范围仅限环境修复（依赖安装、被测服务"
                    "/dashboard 重启、端口占用清理、验证产物重建、裁决场景集"
                    "变更）。环境问题不是产品缺陷：不要打回实现分支、不要修改"
                    "产品代码，不要手动 reset spec 状态。处置完成后，框架将自动"
                    "判定复位路径并触发重验证。"
                ),
            )
            if isinstance(inv, dict) and inv.get("conflict"):
                pipeline._context.logger.info(
                    "pm_engine",
                    f"'{spec_name}' 已有进行中的 Admin 处置，跳过重复呼叫",
                )
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' admin 自动呼叫失败（不阻塞升级）: {e}",
            )
        try:
            pipeline._context.escalation_notifier(
                spec_name=spec_name,
                signal_type="verify_env_blocked",
                severity="critical" if frozen else "warning",
                description=error_msg[:300],
                evidence=(
                    f"spec={spec_name}; " f"report=spec/changes/{spec_name}/verification-report.md"
                ),
                recommended_action=(
                    # add-blocked-reverify-lane D2：处置收尾框架自动复位——
                    # admin 无需手动 reset spec 状态（手动 StateMachine 旁路
                    # 写法失去必要性）。未冻结：等待框架自动重验；已冻结：
                    # 人工检查环境后 unfreeze 清零重试（解冻即清零 rounds）。
                    "无需手动 reset spec 状态：处置完成并写入 result 后，框架"
                    "自动判定复位路径（实现分支已合并→直接重验 testing；"
                    "否则→ready 重实现）"
                    + (
                        f"；已冻结转人工：请检查环境（依赖/服务/端口）后"
                        f"unfreeze_spec 清零重试"
                        + (
                            f"；删除冻结集重新出题将重付出题成本"
                            + (f"（{planner_cost}）" if planner_cost else "")
                            if frozen
                            else ""
                        )
                        if frozen
                        else ""
                    )
                ),
            )
        except Exception as e:
            pipeline._context.logger.warning("pm_engine", f"env 阻塞人工告警失败: {e}")
    except Exception as e:
        # 升级通道自身失败不得抛穿裁决流程
        pipeline._context.logger.warning("pm_engine", f"env 升级通道异常 '{spec_name}': {e}")


def _update_warning_streaks(pipeline, spec_name: str) -> list:
    """更新 warning 连续悬置计数侧车（design D4 / D5）。

    采纳 report.json 后调用：扫描非 PASS 场景——
      - status == warning 且 classification ∈ {flaky, env} 的场景：连续计数 +1；
      - status 为 pass/failed（含被强制重写的 failed）或 classification 为
        product-bug/test-defect 的场景：计数清零。

    返回本轮回填后「连续计数 == 2」的场景 id 列表（即触发 triage 升级的候选），
    调用方据此发告警。侧车文件：``.fenix/verify-progress/<spec>/warning_streaks.json``，
    结构 {scenario_id: 连续轮数}。
    """
    from core.verdict_check import VERDICT_CLASSES, load_report, save_report

    streaks_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "warning_streaks.json"
    )
    streaks = {}
    if streaks_path.exists():
        try:
            loaded = json.loads(streaks_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                streaks = {k: int(v) for k, v in loaded.items() if isinstance(k, str)}
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            streaks = {}

    report = load_report(pipeline._context.project_root, spec_name)
    if report is None:
        return []
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        return []

    triage_candidates = []
    for sc in scenarios:
        if not isinstance(sc, dict):
            continue
        sid = sc.get("scenario_id") or sc.get("id")
        if not sid:
            continue
        status = sc.get("status")
        classification = sc.get("classification")
        # 仅 flaky/env 的 warning 计入连续悬置；product-bug/test-defect 已强制
        # failed（D3），不悬置；pass/failed 清零（D4）。
        if status == "warning" and classification in ("flaky", "env"):
            streaks[sid] = streaks.get(sid, 0) + 1
            if streaks[sid] == 2:
                triage_candidates.append(sid)
        else:
            streaks[sid] = 0

    # 写回侧车
    try:
        streaks_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(streaks_path.parent), prefix=".warning_streaks.", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(streaks, f, ensure_ascii=False, indent=2)
                f.flush()
            os.replace(tmp_path, streaks_path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"warning_streaks 写回失败 '{spec_name}': {e}",
        )
    return triage_candidates


def _warning_stale_triage_alert(pipeline, spec_name: str, scenario_ids: list) -> None:
    """连续 2 轮 warning 场景的 triage 升级告警（design D4 / D5）。

    signal_type=warning_stale_triage，含 spec/场景/轮次/最近证据摘要；
    同时把场景写入下一轮 planner prompt 的「优先复核」注入（与 scenario-freeze
    的基准集注入同一接入点——复用 _scenario_freeze_section 机制：把 triage 场景
    落盘到 verify-progress/<spec>/triage_recheck.json，planner prompt 读取后注入）。
    """
    from core.verdict_check import load_report

    # 证据摘要：从该场景的 evidence.failed_assertions / first_failed_step 摘取
    evidence_lines = []
    report = load_report(pipeline._context.project_root, spec_name)
    latest_round = 2
    if isinstance(report, dict):
        for sc in report.get("scenarios", []) or []:
            if not isinstance(sc, dict):
                continue
            sid = sc.get("scenario_id") or sc.get("id")
            if sid not in scenario_ids:
                continue
            ev = sc.get("evidence") if isinstance(sc.get("evidence"), dict) else {}
            ffs = ev.get("first_failed_step") or ""
            fa = ev.get("failed_assertions") or []
            fa_summary = (
                "; ".join(
                    f"{a.get('type','?')}({a.get('selector','')})"
                    for a in fa
                    if isinstance(a, dict)
                )
                if isinstance(fa, list)
                else ""
            )
            evidence_lines.append(
                f"场景 {sid}（classification={sc.get('classification')}, "
                f"连续 {latest_round} 轮 warning）：{ffs}"
                + (f"；失败断言：{fa_summary}" if fa_summary else "")
            )
    evidence = "\n".join(evidence_lines) or (f"连续 2 轮 warning 场景：{', '.join(scenario_ids)}")

    pipeline._context.escalation_notifier(
        spec_name=spec_name,
        signal_type="warning_stale_triage",
        severity="critical",
        description=(
            f"'{spec_name}' 以下场景连续 {latest_round} 轮均为 warning，"
            f"需人工 triage 甄别是否真缺陷被悬置：{', '.join(scenario_ids)}"
        ),
        evidence=evidence,
        recommended_action=(
            f"人工复核 {', '.join(scenario_ids)} 的真实根因；下一轮验证已将其"
            f"列入优先复核清单（triage_recheck.json）"
        ),
    )
    # 下一轮 planner prompt 优先复核注入（design D5）：落盘 triage_recheck.json
    recheck_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "triage_recheck.json"
    )
    try:
        recheck_path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if recheck_path.exists():
            try:
                data = json.loads(recheck_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    existing = data
            except (json.JSONDecodeError, OSError):
                existing = []
        merged = list(dict.fromkeys(existing + scenario_ids))
        recheck_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"triage_recheck 写盘失败 '{spec_name}': {e}",
        )


def _scenario_defect_reroute_gate(
    pipeline, spec_name: str, _repair_depth: int, judge_result
) -> bool:
    """bug-found 申报打回 implementer 前的分类改道门。

    judge 申报 bug-found 后、打回 implementer 前插入（D1：框架侧机械判定，
    零 token）。report.json 非 PASS 场景全部显式 test-defect/flaky 且
    product-bug=0 → **拒绝打回 implementer**，定向重派 judge 一次（D2）：
    注入改道指令段，责令按原地修复协议申报 scenario-repaired；改道后
    scenario-repaired 沿用既有通道（冻结 diff 记账→重入阶段2/3）。

    预算（D2/D3）：改道重派计入 ``_SCENARIO_REPAIR_MAX_ROUNDS``，与
    scenario-repaired 重入共用 ``_repair_depth`` 计数（防两通道叠加无限重入）。
    预算耗尽仍 bug-found 且 product-bug=0 → 停止重派，升级人工
    （``_send_human_escalation_alert``，附失败清单/classification 分布/
    judge 申报记录），spec 保持 testing。改道路径不触碰 impl_run_budget。

    Returns:
        True 表示已按改道处置（调用方直接 return）；False 表示走现行
        bug-found 路由（打回 implementer）。
    """
    dist = pipeline._scenario_classification_distribution(spec_name)
    if not dist["all_scenario_defects"]:
        pipeline._context.logger.info(
            "pm_engine",
            f"改道门不放行 '{spec_name}'（失败 "
            f"{dist['total']} 个，product-bug={dist['product_bug']}，"
            f"未分类 {dist['unclassified']}）— 走现行 bug-found 路由",
        )
        return False

    # 判定分布记日志留痕（3.1）
    pipeline._context.logger.warning(
        "pm_engine",
        f"场景缺陷改道门触发 '{spec_name}'：失败 {dist['total']} 个全部显式"
        f"test-defect/flaky（分布 {dist['counts']}），product-bug=0 ——"
        f"拒绝打回 implementer，改道重派 judge（深度 {_repair_depth}）",
    )

    if _repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS:
        return pipeline._escalate_scenario_defect_reroute(spec_name, dist, _repair_depth)

    # 写改道指令文件（prompt_builder _scenario_reroute_directive_section 读取）
    directive_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "scenario_reroute_directive.json"
    )
    try:
        directive_path.parent.mkdir(parents=True, exist_ok=True)
        directive_path.write_text(
            json.dumps(dist, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"改道指令文件写失败 '{spec_name}'（仍重派 judge）: {e}",
        )

    try:
        reroute_judge = pipeline._pm.agent_runner.run_planner(spec_name, "judge")
    except Exception as e:
        pipeline._context.logger.error(
            "pm_engine",
            f"改道重派 judge 异常 '{spec_name}'（保持 testing）: " f"{type(e).__name__}: {e}",
        )
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "error": f"场景缺陷改道重派 judge 异常（保持 testing）：{e}",
            },
        )
        return True
    finally:
        try:
            directive_path.unlink()
        except OSError:
            pass

    if not reroute_judge.success:
        # 改道重派失败：取消/派发故障。保持 testing，不升级人工
        # （与裁决重试派发失败同型，温和处置留 error）。
        if getattr(reroute_judge, "cancelled", False):
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道重派 judge 被取消 '{spec_name}' — hold-state（保持 testing）",
            )
        else:
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道重派 judge 派发失败 '{spec_name}' — 保持 testing，"
                f"留 error 待下轮重验: {reroute_judge.error}",
            )
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "error": f"改道重派 judge 派发失败（保持 testing）：" f"{reroute_judge.error}",
                },
            )
        return True

    # 重派结果判定（evo-verifier-result-single-source R1：统一走
    # _read_verdict 入口，主树共享回退须过 role/spec 戳校验）
    reroute_read = pipeline._read_verdict(spec_name)
    if reroute_read.ok and reroute_read.status == "scenario-repaired":
        # 改道后 scenario-repaired：沿用既有通道（冻结 diff 记账 → 重入）
        try:
            freeze_result = pipeline._apply_scenario_freeze(spec_name)
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道后场景冻结记账跳过 '{spec_name}'（异常不阻断）: {e}",
            )
            freeze_result = None
        if isinstance(freeze_result, dict) and freeze_result.get("aborted"):
            # ── 空集显式兜底（evo-planner-scenario-schema-alignment 3.7）──
            # 改道重入路径与 judge 重入同语义：修复后场景集为空 → 拒绝
            # 本次重入、保持原状并留痕，MUST NOT 以空集/未过滤文件进入阶段2。
            reject_detail = "、".join(freeze_result.get("rejected") or [])[:400]
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "error": (
                        f"改道重派 judge 修复后场景集为空（写前预校验整批拒绝，"
                        f"共 {freeze_result.get('total', 0)} 条）— 拒绝本次重入，"
                        f"保持 testing 待人工/下轮处置: {reject_detail}"
                    ),
                },
            )
            pipeline._context.logger.error(
                "pm_engine",
                f"改道重派后无合法场景 '{spec_name}' — 拒绝重入，0 场景不进入"
                f"阶段2: {reject_detail}",
            )
            return True
        pipeline._context.logger.info(
            "pm_engine",
            f"[改道] judge 原地修复采纳 '{spec_name}' — 重入执行"
            f"（第 {_repair_depth + 1}/{_SCENARIO_REPAIR_MAX_ROUNDS} 次修复）",
        )
        pipeline._run_three_stage_verification(spec_name, _repair_depth=_repair_depth + 1)
        return True

    if reroute_read.ok and reroute_read.status == "bug-found":
        # 改道后仍 bug-found：再读分布——
        # 若含 product-bug（judge 改判真产品缺陷）→ 正常打回 implementer 路由；
        # 若仍全场景缺陷且预算耗尽 → 升级人工。
        new_dist = pipeline._scenario_classification_distribution(spec_name)
        if new_dist["product_bug"] > 0 or not new_dist["all_scenario_defects"]:
            pipeline._context.logger.warning(
                "pm_engine",
                f"改道后 judge 改判含产品缺陷 '{spec_name}'（product-bug="
                f"{new_dist['product_bug']}）— 走现行 bug-found 路由",
            )
            return False
        return pipeline._escalate_scenario_defect_reroute(spec_name, new_dist, _repair_depth + 1)

    # 结果不可读/其他状态：fail-closed 保守，保持 testing 等待下轮重验
    pipeline._context.logger.error(
        "pm_engine",
        f"改道重派结果不可读 '{spec_name}'（reason="
        f"{reroute_read.reason if reroute_read.ok is False else '?'}）— "
        f"保持 testing 等待下轮重验",
    )
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "error": "改道重派 judge 结果不可读（保持 testing，等待下轮重验）",
        },
    )
    return True


def _escalate_scenario_defect_reroute(
    pipeline, spec_name: str, dist: dict, _repair_depth: int
) -> bool:
    """改道预算耗尽升级人工：附失败清单/classification 分布/申报记录。"""
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "error": (
                f"场景缺陷改道预算耗尽（{_SCENARIO_REPAIR_MAX_ROUNDS} 轮），"
                f"仍为纯场景缺陷（product-bug=0）— 已升级人工裁决，spec 保持"
                f"testing，不再消耗实现轮预算"
            ),
        },
    )
    pipeline._context.logger.error(
        "pm_engine",
        f"场景缺陷改道预算耗尽 '{spec_name}'（深度 {_repair_depth}）— "
        f"升级人工，不等打回 implementer 修场景",
    )
    pipeline._context.escalation_notifier(
        spec_name=spec_name,
        signal_type="scenario_defect_reroute_exhausted",
        severity="major",
        description=(
            f"'{spec_name}' 验证失败清单全部为场景缺陷（test-defect/flaky）"
            f"且 product-bug=0，改道重派 judge {_SCENARIO_REPAIR_MAX_ROUNDS} "
            f"轮后仍未原地修复完成——已停止重派，升级人工裁决。"
        ),
        evidence=(
            f"spec={spec_name}; classification_distribution="
            f"{json.dumps(dist.get('counts'), ensure_ascii=False)}; "
            f"failed_ids={','.join(dist.get('failed_ids') or [])[:500]}; "
            f"impl_run_budget 未消耗（改道路径不触碰实现预算）"
        ),
        recommended_action=(
            "检查失败场景文件（.fenix/verify-progress/"
            f"{spec_name}/test_scenarios.json）与验证报告，人工裁决："
            "① admin 场景修复通道修场景（schema 门内）；② 确认为真产品缺陷"
            "则重置分类/直接打回 implementer；③ 场景集已过时则删除冻结集批准"
            "重新出题。"
        ),
    )
    return True


def _handle_judge_env_declared(pipeline, spec_name: str) -> bool:
    """judge 自述环境问题时按 inconclusive 处理（不派生 fix）。

    与 _handle_env_blocked_inconclusive 同语义：回 implemented 重派新
    attempt，不 transition bug-found、不派生 fix spec；超限后暂停自动
    重验并暴露错误等待人工（无界重验会烧 token）。
    """
    spec = pipeline._context.state_machine.read_one(spec_name) or {}
    try:
        attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    max_attempts = int(
        pipeline._context.config_reader("verify_engine.inconclusive_max_attempts", 3) or 3
    )
    escalate_attempts = int(
        pipeline._context.config_reader("verify_engine.inconclusive_escalate_attempts", 4) or 4
    )
    note = (
        f"judge 判定 bug-found 但所有 bug 根因均自述为环境/基础设施问题"
        f"（伪失败，不派生 fix），第 {attempts}/{max_attempts} 次重验"
    )

    # ── B7 升级通道（design D6）──
    if attempts >= escalate_attempts:
        # 构造一个简化 report（blocked-env 场景信息从 state 读）：
        # judge 自述环境问题时，blocked-env 数需要从上轮 report 提取，
        # 此处用 _inconclusive_attempts 作为上下文。
        pipeline._write_inconclusive_loop_signal(
            spec_name, attempts, 0, {"scenarios": [], "summary": {"blocked_env": 0}}
        )
        pipeline._context.logger.error(
            "pm_engine",
            f"'{spec_name}' judge 连续 {attempts} 轮均自述环境问题，"
            f"已达升级阈值 {escalate_attempts}，SIGNAL 已写 admin store，"
            f"暂停自动重验等待人工处置",
        )
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "status": "implemented",
                "tester_run": None,
                "error": (
                    f"连续 {attempts} 轮验证均因环境/基础设施问题未完成"
                    f"（judge 自述），已呼叫 Administrator 核查验证环境；"
                    f"人工处置后需清 _inconclusive_attempts 才能恢复自动重验"
                ),
                "_inconclusive_attempts": attempts,
                "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
            },
        )
        return True

    if attempts < max_attempts:
        pipeline._context.logger.warning("pm_engine", f"'{spec_name}' {note}")
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "status": "implemented",
                "tester_run": None,
                "error": note,
                "_inconclusive_attempts": attempts,
            },
        )
        pipeline._context.enqueue(spec_name, "verifier")
        return True

    # 连续 ≥max_attempts 轮均自述环境问题：停止自动重验，暴露错误等待人工。
    pipeline._context.logger.error(
        "pm_engine",
        f"'{spec_name}' 连续 {attempts} 轮 judge 均自述环境问题（伪失败），"
        f"暂停自动重验，请人工检查验证场景/环境",
    )
    pipeline._context.state_machine.update_spec(
        spec_name,
        {
            "status": "implemented",
            "tester_run": None,
            "error": (
                f"连续 {attempts} 轮验证均因环境/基础设施问题未完成"
                f"（judge 自述），请人工检查验证场景/环境；不派生 fix"
            ),
            "_inconclusive_attempts": attempts,
            "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
        },
    )
    return True


def _judge_bugs_declare_env(pipeline, spec_name: str) -> bool:
    """judge 判 bug-found 但其自述根因全部为环境/基础设施问题时返回 True。

    2026-08-28 实证：planner 重新生成的场景用相对 URL "/dashboard"（无效
    URL）+ 幻觉 testid，12 个场景全部在导航步失败；judge 在结果文件中
    自述「这是一个环境问题，而非产品 Bug」，却把 status 标为 bug-found，
    pm_engine 据此派生伪 fix 级联。此处以 judge 自己的根因描述为准：
    所有 bug 均自述环境/基础设施问题时，按「验证没能发生」处理。
    """
    primary = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / ".fenix-run-result.json"
    )
    if not primary.exists():
        return False
    try:
        data = json.loads(primary.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    bugs = data.get("bugs") if isinstance(data, dict) else None
    if not isinstance(bugs, list) or not bugs:
        return False

    def _declares_env(bug) -> bool:
        if not isinstance(bug, dict):
            return False
        text = f"{bug.get('root_cause', '')} {bug.get('description', '')}"
        return any(marker in text for marker in pipeline._context.env_infra_markers)

    return all(_declares_env(bug) for bug in bugs)


def _speculative_bug_found_gate(pipeline, spec_name: str) -> bool:
    """归因分级门禁（add-verdict-credibility-gate / design D2 / Task 2.2）。

    在 bug-found 打回决定前调用：读取 report.json（judge 已增强），框架侧
    机械计算 attribution_level，白屏方向约束强制改写分类，然后判断打回
    依据是否全部为推测级（speculative）——是则抑制 bug-found：
      - 门禁预算内（verify_engine.credibility_gate_max_retries，缺省 1）：
        回 implemented 转重验一次，不向 implementer 带推测信号打回；
      - 预算耗尽：blocked + 告警（attribution_evidence_insufficient），
        交人工复核。

    Returns:
        True 表示已按门禁处置（调用方应 return，不推进 bug-found）；
        False 表示归因有证据支撑（或门禁异常降级不阻断），按既有流程推进。
    """
    try:
        from core.verdict_check import (
            validate_attribution_levels,
            should_suppress_bug_found,
            enforce_blank_screenshot_direction,
            load_report as _load_gate_report,
        )

        gate_report = _load_gate_report(pipeline._context.project_root, spec_name)
        if gate_report is None:
            return False  # 无 report.json，门禁无对象可判，不阻断
        validate_attribution_levels(gate_report)
        for _sc in gate_report.get("scenarios") or []:
            if isinstance(_sc, dict):
                _new_cls = enforce_blank_screenshot_direction(_sc)
                if _new_cls:
                    _sc["classification"] = _new_cls
                    _sc["blank_direction_forced"] = True
        if not should_suppress_bug_found(gate_report):
            # 清空门禁计数：本轮未触发（有证据支撑的归因，不记入 speculative 统计）
            spec_data = pipeline._context.state_machine.read_one(spec_name) or {}
            if spec_data.get("_credibility_gate_attempts"):
                try:
                    pipeline._context.state_machine.update_spec(
                        spec_name,
                        {
                            "_credibility_gate_attempts": 0,
                        },
                    )
                except Exception:
                    pass
            return False

        max_retries = int(
            pipeline._context.config_reader("verify_engine.credibility_gate_max_retries", 1) or 1
        )
        spec = pipeline._context.state_machine.read_one(spec_name) or {}
        gate_attempts = int(spec.get("_credibility_gate_attempts", 0) or 0)
        if gate_attempts < max_retries:
            pipeline._context.logger.warning(
                "pm_engine",
                f"'{spec_name}' 打回归因全部为 speculative（推测级），"
                f"抑制 bug-found——转重验一次"
                f"（第 {gate_attempts + 1}/{max_retries} 次）",
            )
            pipeline._context.state_machine.update_spec(
                spec_name,
                {
                    "status": "implemented",
                    "tester_run": None,
                    "error": (
                        f"归因证据不足待人工复核：全部驱动场景归因"
                        f"为推测级（speculative），已抑制 bug-found "
                        f"打回并重验一次（第 {gate_attempts + 1}/"
                        f"{max_retries} 次）"
                    ),
                    "_credibility_gate_attempts": gate_attempts + 1,
                    "_inconclusive_attempts": 0,
                    # add-verify-parallel-backoff / design D2：计数清零处同步清
                    # 降档并行度（_inconclusive_attempts 同生命周期）。
                    "_verify_parallel_override": None,
                },
            )
            pipeline._context.enqueue(spec_name, "verifier")
            return True

        # 重试预算已耗尽：阻断为 blocked + 告警（交人工复核）
        pipeline._context.logger.error(
            "pm_engine",
            f"'{spec_name}' 归因证据不足待人工复核：连续 "
            f"{gate_attempts} 次推测级归因，门禁预算耗尽，"
            f"阻断为 blocked",
        )
        pipeline._context.state_machine.update_spec(
            spec_name,
            {
                "status": "blocked",
                "error": (
                    f"归因证据不足待人工复核：全部驱动场景归因"
                    f"连续 {gate_attempts} 次为推测级（speculative），"
                    f"门禁重试预算耗尽，已 blocked 等待人工裁决"
                ),
            },
        )
        pipeline._context.escalation_notifier(
            spec_name=spec_name,
            signal_type="attribution_evidence_insufficient",
            severity="major",
            description=(
                f"'{spec_name}' 验证归因证据不足待人工复核："
                f"连续 {gate_attempts} 次驱动场景归因均为推测级"
                f"（speculative），门禁已 blocked 等待人工裁决"
            ),
            evidence=(
                f"spec={spec_name}; max_retries={max_retries}; " f"连续推测轮数={gate_attempts}"
            ),
            recommended_action=(
                "人工核验验证场景与失败断言：若为真·产品缺陷请"
                "在 triage_violations.json 标注后重派 verify；"
                "若为场景缺陷请退回 plan 修复场景"
            ),
        )
        return True
    except Exception as e:
        # 门禁自身异常不阻断既有裁决（治理代码是附加治理，框架级门禁
        # 崩溃按「不阻断」退化——judge 正常裁决继续，避免附加治理代码
        # 成为新单点故障）
        pipeline._context.logger.warning(
            "pm_engine",
            f"门禁校验异常跳过（不阻断裁决）'{spec_name}': " f"{type(e).__name__}: {e}",
        )
        return False


def _write_inconclusive_loop_signal(
    pipeline,
    spec_name: str,
    attempts: int,
    blocked_env: int,
    report: dict,
) -> bool:
    """向 admin store 写 inconclusive_loop SIGNAL（design D6 / Task 5.2）。

    连续 blocked-env 达升级阈值时调用：kind=SIGNAL，type=inconclusive_loop，
    附 spec 名、连续轮数、末轮 blocked_env 数、最近实例探针摘要。admin_monitor
    _detect_family_explosion 摄取后按既有 SIGNAL 通道唤起 Administrator。

    写失败静默降级（信号只是升级通道，spec 的 error 字段已承载人工可见信息），
    返回是否写入成功。
    """
    # 最近实例探针摘要：末轮 blocked-env 场景的 env_probe_detail 里取第一条
    probe_detail = ""
    for sc in report.get("scenarios") or []:
        if not isinstance(sc, dict):
            continue
        if sc.get("status") != "blocked-env":
            continue
        probe_detail = str(sc.get("env_probe_detail") or "").strip()
        if probe_detail:
            break
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(pipeline._context.project_root, pipeline._context.logger)
    try:
        store.append(
            {
                "kind": SIGNAL,
                "signal_type": "inconclusive_loop",
                "spec": spec_name,
                "severity": "major",
                "description": (
                    f"'{spec_name}' 连续 {attempts} 轮验证全部为 blocked-env"
                    f"（环境性失联），已达升级阈值，请 Administrator 核查验证环境"
                ),
                "evidence": (
                    f"spec={spec_name}; 连续轮数={attempts}; "
                    f"末轮blocked_env数={blocked_env}; "
                    f"探针摘要={probe_detail or '无'}"
                ),
                "recommended_action": (
                    "验证环境核查清单：① 被测实例是否就绪（serve/start 命令与端口）；"
                    "② 资源与并行度（max_parallel 是否挤爆实例）；"
                    "③ mock+SSE 链路（mock_api 是否误拦推流、SSE 是否断流）；"
                    "④ 探针摘要（见 evidence）。恢复路径：人工处置后解冻 spec "
                    "（unfreeze）并清 `_inconclusive_attempts`，后续 blocked-env "
                    "轮次从 1 重新计数"
                ),
            }
        )
        return True
    except Exception as e:
        pipeline._context.logger.error(
            "pm_engine",
            f"inconclusive_loop 信号写入失败 '{spec_name}': {e}",
        )
        return False
