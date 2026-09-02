# fast-track-mode — 快速路径运行时能力

## ADDED Requirements

### Requirement: 单 Agent 全包执行

框架 SHALL 为 `mode=fast-track` 的 spec 在进入 ready 状态后派发**单个** fast-track agent run，该 run 在同一上下文中依次完成：实现 → 验证场景设计 → 场景验证 → 结果判定。框架 MUST NOT 为 fast-track spec 派发独立的 planner run 或 verifier run。

#### Scenario: fast-track spec 就绪后单 run 派发
- **WHEN** `mode=fast-track` 的 spec 被调度器拾取且状态为 ready
- **THEN** 框架启动一个 fast-track run（同一 agent 进程、同一上下文、同一 worktree），全程不再派发 planner/verifier run

#### Scenario: 状态机与转换图不变
- **WHEN** fast-track spec 执行期间
- **THEN** 其状态仍沿 `ready → implementing → implemented → testing → verified` 推进，复用现有 VALID_TRANSITIONS，无新增状态

### Requirement: 统一结果文件驱动状态推进

fast-track agent MUST NOT 直接操作状态机。run 结束时输出统一结果文件（含实现产物清单、设计场景、逐场景验证结果、最终判定），daemon 读取并校验该文件后推进状态转换。

#### Scenario: 结果合法则推进
- **WHEN** fast-track run 结束且统一结果文件通过框架校验
- **THEN** daemon 依据结果文件内容推进状态（判定通过 → verified；存在未修复 bug → 按 bug 处理路径）

#### Scenario: 结果文件缺失或非法则不推进
- **WHEN** fast-track run 结束但统一结果文件缺失、格式非法或未通过硬校验
- **THEN** daemon 不推进状态，按失败处理（重派或累计 fail 计数），并在 spec entry 中记录原因

### Requirement: 护栏对单 run 生效

零变更哨、交付物存在性守卫、fail 预算与 token 预算 MUST 对 fast-track run 生效。护栏语义从「run 间」适配为「run 内」，但阻断行为（不合并、不推进、重派、封顶 blocked）与完整模式一致。

#### Scenario: 零变更报成功被拦截
- **WHEN** fast-track run 宣称成功但分支零新提交且零 Edit/Write 工具调用
- **THEN** 零变更哨触发：不合并、不推进，重派 fast-track run，连续 3 次 blocked 交人工

#### Scenario: 交付物缺件被拦截
- **WHEN** fast-track run 宣称成功但 spec 声明的核心交付物未落地
- **THEN** 交付物守卫触发：不合并、不推进，带缺件清单重派

### Requirement: 框架侧硬校验兜底判定

fast-track run 的最终判定 MUST 通过框架侧确定性校验方可视为通过：报告结构完整性、设计场景全量执行（无静默遗漏/豁免逃逸）、逐场景证据存在性。agent 的文本宣称（「验证通过」「测试全绿」）MUST NOT 作为通过依据。校验复用并扩展现有 verdict_check 确定性校验器。

#### Scenario: 判定 pass 但场景证据缺失
- **WHEN** 统一结果文件最终判定为 pass，但存在场景未执行或证据字段为空
- **THEN** 硬校验判定失败，该 spec 不进入 verified，按失败重派 fast-track run

#### Scenario: 判定 fail 时豁免逃逸检查
- **WHEN** 统一结果文件中场景被标记豁免
- **THEN** 硬校验按现有 verdict_check 豁免规则复核豁免合法性，非法豁免视为 bug 未修复

### Requirement: bug run 内修复与超预算升级

fast-track run 验证发现 bug 时 SHALL 在同一上下文内修复并重验，受 fix 预算约束；fix 预算耗尽时框架 MUST 自动将该 spec 升级为完整模式（mode 改写为 `full`）并按完整模式流水线继续处理，MUST NOT 静默丢弃或直接 blocked。

#### Scenario: run 内修复
- **WHEN** fast-track run 验证阶段发现 bug 且 fix 预算未耗尽
- **THEN** 同一上下文内修复后重验，无需跨 agent 传递信息，修复轮次计入 fix 预算

#### Scenario: 超预算升级完整模式
- **WHEN** fast-track run 内修复轮次耗尽 fix 预算仍存在未修复 bug
- **THEN** 框架将该 spec 的 mode 改写为 `full`，保留已有实现成果（worktree/分支），按完整模式继续走 planner + verifier 流水线，并向用户记录升级原因

### Requirement: worktree 全生命周期复用与合并语义

fast-track run SHALL 在同一 worktree 内完成实现与验证（验证时直接在该 worktree 运行被测应用）；成功路径的 merge 语义（含派发前 spec 目录提交 ensure_spec_committed）MUST 与完整模式保持一致。

#### Scenario: 同一 worktree 完成实现与验证
- **WHEN** fast-track run 执行中
- **THEN** 实现与验证均发生在同一 worktree，验证阶段的应用运行环境基于该 worktree 代码，无跨 worktree 的代码同步步骤

#### Scenario: 成功合并语义一致
- **WHEN** fast-track spec 通过硬校验进入 verified 并推进 done
- **THEN** merge-back 行为与完整模式一致（分支保留、主树合并、spec 目录已提交前提成立）
