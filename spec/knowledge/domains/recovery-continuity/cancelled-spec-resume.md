<!-- knowledge: capability=cancelled-spec-resume rev=1 sources=spec/archive/2026-09-25-add-cancelled-spec-resume-action -->

# 取消保持 SPEC 的恢复运行动作

对处于取消保持态（`_cancelled_hold`）的 SPEC 提供界面一键恢复：复位 ready 并按保留分支续做，无可保留分支时降级全新重派。

## 现行规则

- 取消保持态可见：Dashboard SPEC 摘要（`/api/specs`）与详情（`/api/specs/<spec>`）下发 `cancelled_hold` 布尔字段，取值须经归一化（`str(v).strip().lower() in ("true","1","yes")`，与 `parse_state` 对 `frozen` 同口径）；STATE.md 序列化 Python 字面量（`_cancelled_hold: False`），裸 `bool(entry.get(...))` 会把文本 `"False"` 当真值，禁用。
- 恢复端点 `POST /api/spec-resume?project=<name>&spec=<name>` 命中时单次原子写：`status: ready`（携带 status 即由 `update_spec` 自动清 `_cancelled_hold`）；`branch` 写解析出的保留分支、`implementer_run` 保留原锚点；`_recovery_resume: true`（dispatch 据此在保留分支 worktree 内续做）；`tester_run` 清空，`_retry_count` / `_merge_fp` / `_merge_streak` / `_redispatch_same_cause_streak` / `_redispatch_cause_fp` 归零（防陈旧验证锚点被误读为在飞、陈旧 merge-back 计数触发误熔断/误告警）；`error` 写恢复留痕文案（含原状态与 resume preserved branch 语义）。
- 保留分支解析复用 `_resolve_preserved_branch` 共享判定：STATE.branch → 在册 worktree → 分支命名空间枚举三层回落 + `rev-list main..branch` 非空闸门 + `resolve_resume_site` 载体三态；不新建平行副本。判定通过后写 `scheduling_kick` 信号即时唤醒派发（daemon 1s 粒度消费，无需等待周期扫描）；信号写失败如实回传 warning，STATE 已变更不回滚。
- 无可保留分支（三层锚点均不可得 / 分支相对 main 零提交 / 载体不可用，且共享判定已实际运行给出结论）→ 返回 `ok: true` 携带 `degraded: true` 与降级原因；STATE 落 ready、锚点清空、不置 `_recovery_resume`，daemon 走普通全新派发；降级打 WARNING 留痕。
- 载体工具不可用（WorktreeManager 构造失败，保留判定根本未运行）→ 返回 `ok: false`，STATE 零变更；不得以「无可保留分支」为由降级清锚点——那会把仍可续做的保留分支从 STATE 脱钩。
- 拒绝语义（均零 STATE 变更）：spec 不存在 → not found；终态（done/pushed）→ 终态不可恢复；`_cancelled_hold` 非 true（按归一化布尔读值判定，禁裸真值判定，否则文本 `False` 误纳非保持态 SPEC 并被强置 ready）→ 幂等拒绝并附原因；冻结态（结构化 frozen 标记或文本前缀命中）→ 须先解冻，禁止绕过。
- 「修改状态」弹窗对 `cancelled_hold` 为 true 的非终态 SPEC 渲染「恢复运行」区块，文案说明恢复将复位 ready 并按保留分支续做（无可保留分支则全新重派）、消耗一次实现尝试预算；点击弹确认框，确认后按返回结果（成功/降级/拒绝）给出对应反馈；非取消保持态不渲染该区块。

## 溯源

- 2026-09-25 add-cancelled-spec-resume-action — 新增取消保持态可见字段、恢复运行端点（含降级与拒绝语义）与弹窗恢复区块
