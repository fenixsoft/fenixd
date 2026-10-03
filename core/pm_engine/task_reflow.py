"""task_reflow.py — task-gap 滞留 SPEC 的人工回炉动作（fix-impl-tasks-completion-gate P1′/D8）。

「回炉」= 把因 verified→done 任务完成度门禁（`_task_completion_blocker`）拦截而
滞留在 verified 的 SPEC 复位为 ready，使其可被 daemon 重新派发实现者承接剩余
任务。本模块是**判定与执行的单一实现点**（D8）：Dashboard 路由与 CLI reflow
子命令均只做参数解析与结果呈现，MUST NOT 在两侧各自复写一套判定逻辑——
add-spec-review-gate 的教训正是 CLI 通道绕过评审分流（cmd_promote 硬编码 ready，
不消费 promote_drafted 的 next_status），同一形态的坑不重踩第二次。

**开放条件**（全部满足才允许执行）：
1. 目标 SPEC 存在（STATE.md 有该条目）；
2. 其 `status` 恰为 `verified`；
3. 其 `error` 字段以 `TASK_GAP_ERROR_PREFIX`（"task-gap:"）开头——即确系任务
   完成度门禁写入的结论；
4. 该 SPEC 未被冻结（`frozen` 标记为假）。

**执行语义**：经 `StateMachine.update_spec` 原子写回 `status = "ready"` 与
`error = null`（`update_spec` 对携带 `status` 的更新会自动解除取消保持标记，
语义与既有面板重派 / admin 处置复位一致）。写回后重读复核（code-review
b790603c7cae）：读快照判 verified 与写回之间无原子性，窗口内该 SPEC 已被
verified→done 门禁放行（total_duration 残留判别，全库唯一写点在门禁放行
分支）时，回写恢复 done 并如实返回失败。MUST NOT 直接改写 tasks.md、
MUST NOT 修改实现尝试预算计数（`_impl_run_budget_used`）、MUST NOT 触碰
`frozen` / `frozen_until` / `start_after`，MUST NOT 绕过 daemon 的后续派发
闸门（依赖、start_after、退避、冻结检查照常生效）。

复位后 MUST 在 `.fenix/PROJECT_LOG.md` 追加一条可追溯记录（含 SPEC 名、原状态、
缺口任务清单、动作来源）——PROJECT_LOG 追加失败仅记 warning（留痕是附加物，
不阻塞复位）。

**返回值契约**（Dashboard / CLI 共用，对齐 promotion.promote_drafted 风格）：
    {"ok": True, "spec": ..., "status": "ready", "gap_tasks": [...]}        合规复位成功
    {"ok": False, "found": False, "reason": "..."}                           SPEC 不存在
    {"ok": False, "found": True, "reason": "..."}                            其余拒绝（非 verified /
                                                                              error 非 task-gap 前缀 /
                                                                              冻结态 / 幂等重复）
"""

from datetime import datetime, timezone
from pathlib import Path

from core.pm_engine import TASK_GAP_ERROR_PREFIX  # noqa: E402


def reflow_spec(
    project_root, spec_name: str, *, state_machine, logger, source: str = "api"
) -> dict:
    """task-gap 滞留 verified SPEC 的人工回炉（判定 + 执行 + 留痕 单一实现点）。

    Args:
        project_root: 项目根路径（PROJECT_LOG.md 定位）。
        spec_name: SPEC 名称。
        state_machine: StateMachine 实例（读取状态与原子写回）。
        logger: 日志实例（需有 info/warning/error 方法）。
        source: 动作来源（"api" / "cli"，写入 PROJECT_LOG 留痕）。

    Returns:
        {"ok": True, "spec": ..., "status": "ready"} — 合规复位成功；
        {"ok": False, "found": False, "reason": ...} — SPEC 不存在；
        {"ok": False, "found": True, "reason": ...} — 拒绝（非 verified /
                                                      error 非 task-gap 前缀 /
                                                      冻结态 / 写回期间被并发冻结 /
                                                      写回窗口内已被门禁放行为 done）。
    """
    from core.state_machine import FROZEN_FIELD

    entry = state_machine.read_one(spec_name)
    if entry is None:
        return {"ok": False, "found": False, "reason": f"spec '{spec_name}' not found in STATE.md"}
    entry = dict(entry) if isinstance(entry, dict) else {}

    # ── 开放条件判定（全部满足才放行） ─────────────────────────────
    status = entry.get("status", "")
    if status != "verified":
        return {
            "ok": False,
            "found": True,
            "reason": (
                f"spec '{spec_name}' 当前状态为 '{status}'，不在可回炉形态"
                f"（仅 verified 且 error 为 task-gap 缺口结论可回炉）"
            ),
        }
    err = entry.get("error") or ""
    if not (isinstance(err, str) and err.startswith(TASK_GAP_ERROR_PREFIX)):
        return {
            "ok": False,
            "found": True,
            "reason": (
                f"spec '{spec_name}' 未检出任务缺口结论（error 不以 "
                f"'{TASK_GAP_ERROR_PREFIX}' 开头）——不做回炉"
            ),
        }
    if entry.get(FROZEN_FIELD):
        return {
            "ok": False,
            "found": True,
            "reason": f"spec '{spec_name}' 处于冻结态——须先解冻再回炉",
        }

    # ── 执行：原子写回 status=ready + error=null（update_spec 不做状态机合法性
    #    校验，正是本动作用得上的地方：verified→ready 不在 VALID_TRANSITIONS）──
    # applied_out 收集写回实际生效字段（code-review b7a0f425b6bb）：读快照判
    # 冻结与写回之间无原子性，窗口内该 SPEC 被并发冻结时 _apply_updates_entry
    # 会剥离 status 写（仅落 error=null）——update_spec 照常返回 True，但回炉
    # 实际未发生。据 _stripped 痕迹识破该假成功：如实返回失败并记 warning，
    # 不落 PROJECT_LOG 成功留痕（日志语义与真实状态一致；被清掉的 task-gap
    # error 由下一次 verified→done 门禁尝试重写）。
    applied: dict = {}
    ok = state_machine.update_spec(
        spec_name, {"status": "ready", "error": None}, applied_out=applied
    )
    if not ok:
        return {
            "ok": False,
            "found": True,
            "reason": f"spec '{spec_name}' 状态写回失败（STATE.md 原子写失败）",
        }
    if "_stripped" in applied:
        logger.warning(
            "pm_engine",
            f"回炉未生效 '{spec_name}'（来源={source}）：写回期间该 SPEC 已被"
            f"并发冻结，status='{applied['_stripped']}' 写被剥离（error 已随"
            f"更新清空，待下次门禁重写）",
        )
        return {
            "ok": False,
            "found": True,
            "reason": f"spec '{spec_name}' 写回期间已被冻结，回炉未生效（status 写被剥离）",
        }

    # ── 写回后重读复核（code-review b790603c7cae）：_stripped 只能识破「并发
    #    冻结剥离 status 写」一种竞态，普通状态转移竞态不设防——读快照判
    #    verified 与本写回之间，verified→done 门禁恰好放行（人工补勾任务后
    #    engine._on_spec_verified 自动重试转移）时，update_spec 的无条件
    #    status=ready 写会把已 done 的 SPEC 盲覆盖回 ready，触发对已交付成果
    #    的重派实现——正是本模块设计要避免的反向处置。state_machine 无 status
    #    条件写公开原语（set_impl_budget_used_if_unchanged 仅覆盖预算字段，
    #    新增通用原语属清单外改动），故取写回后重读校验的最小侵入修法：
    #    total_duration 是 done 落定的全库唯一残留写点（门禁放行转移成功后
    #    落盘），快照无而有即判「窗口内已 done」——状态仍为 ready（尚无并发
    #    派发消费这个错误的 ready）则回写恢复 done；已推进则不回写干预、只
    #    告警。两种异常路径均如实返回失败、不落 PROJECT_LOG 成功留痕（日志
    #    语义与真实状态一致，同 _stripped 分支口径）。
    post = state_machine.read_one(spec_name)
    post = dict(post) if isinstance(post, dict) else {}
    if not post:
        logger.warning(
            "pm_engine",
            f"回炉写回后复核失败 '{spec_name}'（来源={source}）：SPEC 已不在 "
            f"STATE.md（并发驱逐/归档），回炉结果不可判读",
        )
        return {
            "ok": False,
            "found": True,
            "reason": f"spec '{spec_name}' 写回后复核失败（SPEC 已不在 STATE.md）",
        }
    # total_duration 用 is not None 判（门禁放行分支写 runs 求和值，合法写 0）
    _done_in_window = (
        post.get("total_duration") is not None
        and entry.get("total_duration") is None
    )
    if _done_in_window or post.get("status") == "done":
        _post_status = post.get("status", "")
        if _post_status == "ready":
            # 仍是 ready → 我们的误覆盖就是当前态，回写恢复 done（有意盲写：
            # 任务已全部可确认完成、门禁已放行，done 是该 SPEC 的真实归宿）
            restored: dict = {}
            state_machine.update_spec(
                spec_name, {"status": "done"}, applied_out=restored
            )
            if "_stripped" in restored:
                logger.warning(
                    "pm_engine",
                    f"回炉误覆盖回滚失败 '{spec_name}'（来源={source}）：恢复 "
                    f"done 的写回又被并发冻结剥离——须人工核对状态",
                )
            else:
                logger.warning(
                    "pm_engine",
                    f"回炉写回与门禁放行竞态 '{spec_name}'（来源={source}）："
                    f"写回窗口内该 SPEC 已被 verified→done 门禁放行，ready 写"
                    f"误覆盖已交付状态（total_duration 残留证实）——已回写恢"
                    f"复 done，本次回炉不生效",
                )
            _rollback_note = "（已回写恢复 done）"
        else:
            # 已被并发写者推进（如派发立即消费了误覆盖的 ready）→ 不再盲写
            # 对打在飞转移，告警交人工对账
            logger.warning(
                "pm_engine",
                f"回炉写回与门禁放行竞态 '{spec_name}'（来源={source}）：写回"
                f"窗口内该 SPEC 已被门禁放行为 done、现状态 '{_post_status}'"
                + ("（total_duration 残留证实）" if _done_in_window else "")
                + "——不回写干预，须人工核对状态",
            )
            _rollback_note = f"（状态已推进至 '{_post_status}'，未回写）"
        return {
            "ok": False,
            "found": True,
            "reason": (
                f"spec '{spec_name}' 写回窗口内已被 verified→done 门禁放行，"
                f"回炉写回误覆盖已交付状态{_rollback_note}"
            ),
        }

    # ── 留痕：PROJECT_LOG.md 追加可追溯记录（失败仅 warning，不阻塞复位）──
    gap_tasks = _extract_gap_tasks(err)
    try:
        proot = Path(project_root)
        log_path = proot / ".fenix" / "PROJECT_LOG.md"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                f"\n- [{timestamp}] 回炉(task-reflow, 来源={source}): "
                f"SPEC「{spec_name}」verified→ready（task-gap 缺口，人工回炉）；"
                f"缺口任务: {', '.join(gap_tasks) if gap_tasks else '见 error 原文'}"
            )
    except OSError as e:
        logger.warning(
            "pm_engine",
            f"回炉 PROJECT_LOG 留痕失败 '{spec_name}'（非阻塞）: {e}",
        )

    logger.info(
        "pm_engine",
        f"回炉成功 '{spec_name}'（来源={source}）: verified→ready，"
        f"缺口任务 {len(gap_tasks)} 项——daemon 将按既有逻辑重新派发实现者",
    )
    return {"ok": True, "spec": spec_name, "status": "ready", "gap_tasks": gap_tasks}


def _extract_gap_tasks(error: str) -> list:
    """从 task-gap: 错误文案提取缺口任务 id 清单（按 、/,/，/;/；/:/：/空白 分隔，id 尾部可带 。/./;/； 标点）。

    提取失败/无 id → 空清单（留痕退化为引用 error 原文，不伪造）。
    任务 id 合法性判定与 parse_tasks_md 同源（core.run_task_track.is_task_id）：
    形如 ``1.1`` / ``1.2b``（字母后缀为合法补充任务形态）。
    """
    import re

    from core.run_task_track import is_task_id

    if not error:
        return []
    ids = []
    for part in re.split(r"[、,，;；:：\s]+", error[len(TASK_GAP_ERROR_PREFIX) :]):
        part = part.strip()
        # 容错：文案里的 id 可能带尾部标点（如 "1.2b。"），剥离后判定
        part = part.rstrip("。.；;")
        if is_task_id(part):
            ids.append(part)
    return ids
