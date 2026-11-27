# 对照基线：审查车道纯文本轮占比（2026-11-27 实测）

## 取样与口径

- 数据源：`.fenix/runs/archive/code-review-*.jsonl`（14 个档案）与 `code-fix-*.jsonl`（99 个档案）中的 `"type": "run_metrics"` 事件行。**不取**终态 result 行——终态行不含 `turns` / `text_turns` / `model` 字段。
- 纯文本轮占比 = `text_turns / turns`；离群判据沿用 midflight-outlier-screening：`turns > 100` 且占比 `> 50%`。
- 复现：按上述 lane 前缀扫档案，逐行解析 JSON，取 `type == "run_metrics"` 的事件行聚合。

## code-review 车道

- 事件行 15 条（14 个档案）：14 条顶层 `model` 为 `glm-5.3-flash`；`code-review-1795536116` 另含 1 条 `deepseek-flash` 子面 run_metrics（847 轮 / 24 纯文本轮 = 2.83%）。车道内模型方差极小。
- 命中离群判据 3 个：
  - `code-review-1795190463`：2364 轮 / 1193 纯文本 = **50.47%**（glm-5.3-flash）
  - `code-review-1795277035`：3610 轮 / 2102 纯文本 = **58.23%**（glm-5.3-flash）
  - `code-review-1795709077`：4045 轮 / 2042 纯文本 = **50.48%**（glm-5.3-flash）

## code-fix 车道

- 事件行 101 条（99 个档案）：`glm-5.3-flash` 97 条、`deepseek-flash` 4 条。
- 命中离群判据 4 个（全部 glm-5.3-flash）：
  - `code-fix-1794656523`：123 轮 / 74 纯文本 = **60.16%**
  - `code-fix-1795322096`：124 轮 / 70 纯文本 = **56.45%**
  - `code-fix-1795324297`：117 轮 / 60 纯文本 = **51.28%**
  - `code-fix-1795638245`：106 轮 / 61 纯文本 = **57.55%**
- deepseek-flash 旁证（未命中判据的低占比样本）：`code-fix-1795554487` 391 轮 / 35 = **8.95%**；`code-fix-1795122716` 418 轮 / 38 = **9.09%**。

## 归因事实

code-fix 的既有「输出纪律」节（agents/code-fix.md，2026-09-23 由 4a2454707 引入）生效期间，该车道仍 4 次命中离群判据（上列 60.16% / 56.45% / 51.28% / 57.55%，turns 均 > 100）。故本次对 code-fix 是「既有节形态升级 + 归因修正」，不是「从无到有」；对 code-review 是新增纪律节（原模板仅「完成后」有收尾统计约束）。

## 后续观察与止损

登记于 `.fenix/todo.md`（2026-11-27）：后续观察窗由自省车道按 midflight-outlier-screening 既有检测复看两车道占比；按 `spec/knowledge/domains/agent-runtime/planner-plan-output-discipline.md` 止损判据——连续 3 轮迭代（观察窗）占比无压降，转模型版本对照处置，不在提示词层继续迭代。

（注：原「94/94」与「3 例 deepseek 9.1%-41%」经实测不成立，已按上文可复现数值替换。）
