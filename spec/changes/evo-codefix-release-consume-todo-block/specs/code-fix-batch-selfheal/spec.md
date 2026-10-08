# code-fix-batch-selfheal 变更

## MODIFIED Requirements

### Requirement: 人工解除跳过留痕与登记核销对齐

release_failed_batch 被调用（无论经 daemon 内路径还是带外脚本）时写结构化留痕，且解除与登记核销两条生命周期终点必须对齐：解除不得产生无人核销的孤儿登记块。

#### Scenario: 解除即同步核销登记块

- **When** release_failed_batch 成功删除/收缩注册表记录
- **Then** 同一调用序列内 best-effort 核销 todo.md 对应登记块（注记写明解除时刻与 fix-failed-release.jsonl 留痕行）；todo 写失败不阻断解除，留痕行记录 todo 块处理结果（consumed / not_found）

#### Scenario: 预算内自动释放同权对齐

- **When** release_retryable_failed_batches（新链启动预算内自动释放）删除注册表记录
- **Then** 与人工解除同权：写 fix-failed-release.jsonl 留痕（released_by=auto-budget）并同步核销对应登记块

#### Scenario: 登记块已损毁成裸标题壳

- **When** 被核销登记块的正文已丢失、仅剩标题行
- **Then** 按标题兜底移除残骸，不波及他批登记块

#### Scenario: 带外调用留痕（既有，不回归）

- **When** release_failed_batch 经带外 python3 -c 直调（无 logger）
- **Then** fix-failed-release.jsonl 留痕行照写（含 todo 块处理结果），不要求 daemon 日志