# code-fix-batch-selfheal 变更

## MODIFIED Requirements

### Requirement: 失败批登记的闭环核销

达自动重试上限的失败批记录（fix-failed.json）与其告警、todo 登记必须具备生命周期终点：当被跳过条目已全部终态（resolved/ignored）时自动核销并收口告警；部分终态时同步剩余 open 数；人工解除跳过必须留痕，且解除与登记核销两条生命周期终点必须对齐——整批解除不得产生无人核销的孤儿登记块，部分解除不得提前核销仍在跳条目的登记块。

#### Scenario: 被跳过条目全部终态后自动核销

- **When** 周期对账（批收尾/合回核销点或新链启动簿记块）发现某失败记录的被跳过条目全部处于终态
- **Then** 该记录写入 consumed_at 与终态分布注记、不再提示人工排查；对应 code_fix_retry_budget_exhausted 告警经 mark_signal_handled 收口（action_taken 附 N resolved / M ignored）

#### Scenario: 部分终态同步剩余 open 数

- **When** 对账时被跳过条目仅部分终态
- **Then** 更新记录的 open_remaining，不收口告警、不标记核销

#### Scenario: 重复核销幂等

- **When** 同一失败记录被对账逻辑再次命中且已核销
- **Then** 不重复写注记、不重复收口告警、不报错

#### Scenario: 人工解除跳过留痕

- **When** release_failed_batch 被调用（无论经 daemon 内路径还是带外脚本）
- **Then** 写一行结构化留痕（释放记录数、item_ids 摘要、todo 块处理结果 consumed/not_found，追加到 `.fenix/code-review/fix-failed-release.jsonl`，不经 daemon logger 亦可追溯）；调用方传入 logger 时另写一行 daemon 日志

#### Scenario: 整批解除即同步核销登记块

- **When** release_failed_batch 整批删除注册表记录成功
- **Then** 同一调用序列内 best-effort 核销 todo.md 对应登记块（注记写明解除时刻与 fix-failed-release.jsonl 留痕行）；核销定位按条目集整行精确匹配，不误命中清单为其前缀扩展的他批登记块；todo 写失败不阻断解除，留痕行记录 not_found

#### Scenario: 部分解除不核销登记块

- **When** release_failed_batch 部分解除（收缩记录、剩余条目仍在册仍跳过）
- **Then** 不核销 todo.md 对应登记块（剩余条目的人工排查登记保留），登记块由既有 consume 闭环在剩余条目全部终态时核销

#### Scenario: 预算内自动释放留痕

- **When** release_retryable_failed_batches（新链启动预算内自动释放，打标墓碑保留在册）释放记录
- **Then** 写 fix-failed-release.jsonl 留痕（released_by=auto-budget）；不触 todo 登记块——预算内记录未达登记阈值本无登记块，在册墓碑由既有 consume 闭环核销

#### Scenario: 登记块已损毁成裸标题壳

- **When** 被核销登记块的正文已丢失、仅剩标题行
- **Then** 按标题兜底移除残骸，不波及他批登记块

#### Scenario: 台账读取失败不阻断主流程

- **When** 核销对账时台账读取失败
- **Then** 按空集 fail-open 跳过本轮核销，不阻断批收尾/链启动主流程
