# fix-timeline-substring-leak 设计

## Context

`get_spec_timeline`（core/dashboard/data.py:2963）从 daemon 日志构建时间轴，行归属判定有两处形态：

1. `Transition:` 行：`re.compile(r"Transition: " + re.escape(spec_name) + r"\s+...")`——名字后要求紧跟空白，前缀名不误命中（已安全）。
2. `Updated SPEC` 行（data.py:3018）：`if "Updated SPEC" in msg and spec_name in msg:`——**子串匹配**。日志文案形态为 `Updated SPEC '<name>'`（单引号包裹，写点唯一于 state_machine.update_spec 的 logger 调用），前缀名 spec 因此吸收姊妹 spec 的全部状态更新，进入 `status_updates` → 打回重建分支按时间合流推演 current 指针 → 被泄漏项推到 pushed → 基 spec 自己的恢复直写行显示成「已推送→就绪」。

次生问题：重建节点无同行 err 时落 `_backtrack_reason` 兜底「状态回退」（前向节点也拿此文案）；`errors_at` 就近覆写（≤600s）专为此类兜底节点用最近 error 精化——恢复行 error（"Recovered from interrupted state: implementing"）因此贴满全部泄漏卡。前端 `detail.tsx:846` `isRollback = !!item.reason` 使任何带 reason 的前向节点挂「↩ 状态回退」徽标。

## Goals

- 时间轴按 spec 名精确隔离，姊妹 spec 零泄漏
- from 推演不被外部状态污染；恢复直写行显示真实 from
- 方向语义单源：后端 backward 字段，前端徽标跟随

## Decisions

- **D1 全匹配锚点**：`Updated SPEC` 判定改 `f"'{spec_name}'" in msg`。实现前 grep 全库确认「Updated SPEC」日志文案写点唯一（state_machine.update_spec）且均为引号包裹形态；若有未引号形态写点，先统一文案再匹配。
- **D2 前向节点 reason 语义**：打回重建分支中，节点方向按 `_LIFECYCLE_ORDER` 判定；前向节点无同行 err → reason 置空（不再落 `_backtrack_reason`），使其可并入折叠链（与 Transition 前向节点行为一致）；有同行 err → reason=err 且 `_precise_reason=True`（现状保留）。回退节点维持现状（err 精确 / 兜底文案）。就近 error 覆写守卫不变——D2 后前向无 err 节点 reason 为空，天然不在覆写射程。
- **D3 backward 字段**：state 节点统一输出 `backward: bool`（`_LIFECYCLE_ORDER.get(to, 9) < _LIFECYCLE_ORDER.get(frm, 9)`，与 Transition 回退判定同式）。Transition 路径现有 `_LIFECYCLE_ORDER` 判定复用为该字段来源（原来只用于决定是否填 reason）。
- **D4 前端兼容**：`detail.tsx` 徽标判定 `item.backward === true`，字段缺失（旧快照/归档数据）回退 `!!item.reason`。reason 文案展示逻辑不动。
- **D5 审计不扩 scope**：`_admin_events_for_spec` / `get_runs` 的名称过滤若存在同款子串匹配，仅在收工 findings 登记不本次修复（无实证泄漏，避免范围膨胀）。

## Risks

- 日志文案若有其它写点不带引号 → 全匹配漏计：D1 的 grep 前置核对兜住。
- 前向无 err 节点 reason 置空后进入折叠链：展示上合并为链（chain 全量下发，符合既有折叠设计意图，非回归）。
- 前端旧数据（无 backward 字段）走回退分支：行为与现状一致，无回归面。
