# code-fix-batch-selfheal 变更

## MODIFIED Requirements

### Requirement: 失败批登记的闭环核销

达自动重试上限的失败批记录（fix-failed.json）与其告警、todo 登记必须具备生命周期终点：当被跳过条目已全部终态（resolved/ignored）时自动核销并收口告警；部分终态时同步剩余 open 数；人工解除跳过必须留痕。

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
- **Then** 写一行结构化日志（释放记录数与 item_ids 摘要），使带外经 daemon 的调用可追溯

#### Scenario: 台账读取失败不阻断主流程

- **When** 核销对账时台账读取失败
- **Then** 按空集 fail-open 跳过本轮核销，不阻断批收尾/链启动主流程