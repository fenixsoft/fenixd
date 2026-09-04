# implementer-deliverable-gate 增量规格

## ADDED Requirements

### Requirement: 交付物路径提取
系统 MUST 能从 SPEC 的 tasks.md 与 proposal.md 中提取声明交付的文件路径集合，仅识别显式路径形态（反引号包裹、代码块、`路径:` 前缀行）下匹配 `core/**`、`tests/**`、`.fenix/**`、`scripts/**` 的条目；提取不到任何路径的 SPEC MUST 跳过守卫。

#### Scenario: 从 tasks 与 proposal 提取路径
- **WHEN** SPEC 文档中声明了 `core/dashboard/static/v2/pages/config.json` 等 5 个交付路径
- **THEN** 守卫提取到 5 个路径组成的清单，作为校验基准

#### Scenario: 无可提取路径时跳过
- **GIVEN** 某 SPEC 文档不含任何显式交付路径
- **WHEN** 实现 run 收工
- **THEN** 守卫不生效，按既有收工路径处理（行为与守卫上线前一致）

### Requirement: 收工时存在性校验
实现 run 声明成功后、merge 之前，系统 MUST 校验提取清单中每个路径在 worktree 工作树内存在；任一缺件 → 本次 run 按失败处置。

#### Scenario: 缺件阻断 merge
- **GIVEN** 清单含 config.json 且 worktree 中该文件不存在
- **WHEN** 实现 agent 报成功
- **THEN** 不执行 merge、不推进状态
- **AND** error 记录缺件路径清单（含「交付物守卫」字样），按既有重试路径重派实现

#### Scenario: 全部存在时放行
- **GIVEN** 清单全部路径在 worktree 存在
- **WHEN** 实现 agent 报成功
- **THEN** 走既有 merge 与推进路径，守卫不产生额外状态变更

### Requirement: 校验成本约束
守卫校验 MUST 为纯文件系统存在性检查（单轮 O(清单大小) 次 stat），MUST NOT 触发测试执行、LLM 调用或网络请求。

#### Scenario: 零额外成本
- **WHEN** 守卫执行
- **THEN** 无 LLM/测试/网络调用，仅文件 stat
