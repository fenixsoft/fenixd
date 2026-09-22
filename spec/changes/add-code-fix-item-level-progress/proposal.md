# add-code-fix-item-level-progress

## Why

code-fix 自动修复车道的进度粒度是**批级**：`fix-progress.json` 只在批生命周期收尾（修复 run 结束 → 回归通过 → 合回 → 核销台账）时更新 `done`。以 fenixd 实测数据计，一批 20 条约 60 分钟（2026-09-22 第 1 批 21:15→22:1x），全程 270 条 ≈ 14 小时——期间用户在进度卡片上看到的始终是 `0%`，无法区分「正常工作中」与「卡死」，当日实际发生了两次误判（用户两次质询停摆）。

而 agent 侧的条级进度源**在契约上已存在**：`agents/code-fix.md` 要求每修完一条立即向 `fix-out-<run_id>.jsonl` 追加一行 `{item_id, status: fixed|skipped, file}`，编排侧也已有解析函数 `core/code_fix.py read_fix_out()`——缺的只是把「当前批的 worktree + run_id」暴露给读侧并合成进进度接口。

## What Changes

- `fix-progress.json` 新增 `worktree` / `run_id` / `batch_total` 三个批上下文字段（编排器在建树成功后、agent run 启动前写入；`run_id` 由编排器预生成并经 `run_code_fix` 既有 `run_id` 形参传入，保证 run 在飞期间读侧即可解析；批收尾清除）。
- `read_progress()` 在 `running=true` 且批上下文可用时，经 `read_fix_out()` 实时合成条级字段：`item_done`（本批已处置条数，按 item_id 去重）、`current_item`（最近一条处置结果对应的台账条目摘要）。
- Dashboard 转导层透传新字段；`CodeFixProgressCard` 增加条级文案「本批已处置 N/M 条 · 刚完成：<file> <标题>」（M=`batch_total`）。
- 全链路容错：out 文件缺失/损坏/批上下文缺失时条级字段回退 null，前端不显示误导性数字——批级行为与现状完全一致（纯增量，零行为变更）。

## Capabilities

### New Capabilities

- `code-fix-item-level-progress`: code-fix 车道批内条级进度合成与展示——读侧经增量产物文件实时计算本批已处置条数与最近处置条目，缺失场景安全回退。

### Modified Capabilities

<!-- 无既有能力的需求级变更：code-fix-progress 的既有字段与批级语义保持不变，本变更为纯增量字段。 -->

## Impact

- `core/code_fix.py`（read_progress 合成 + 编排器写批上下文）
- `core/dashboard/data/code_review.py`（转导新字段）
- `core/dashboard/static/src/pages/projects/components/CodeFixProgressCard.tsx`（条级文案）
- 无状态机变更、无并发模型变更、无数据迁移；旧进度文件缺新键按缺省回退，向后兼容。
