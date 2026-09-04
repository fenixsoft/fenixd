# Proposal: add-fast-track-mode

## Why

当前 Fenix 全流程以状态机驱动、多 Agent 分段执行（implementer → planner → verifier），各 Agent 在各自上下文中重复探索代码库，信息靠 spec 文件 / scenarios.json / verify report 传递。这对复杂需求是合理的，但对简单需求而言：每个 Agent 的冷启动探索开销重复支付、上下文信息传递损耗大、多 run 串行等待拉长交付时间。需要一条快速路径：简单需求由单个 Agent 在同一上下文中连续完成实现、场景设计、验证与判定，省略跨 Agent 的信息重复。

## What Changes

- **SPEC 元数据新增执行模式字段**：`mode: fast-track | full`（缺省 `full`），由 fenix-new 创建时写入 spec 元数据。
- **fenix-new 模式建议机制**：需求 Agent 在澄清需求时评估复杂度，对未指定模式的用户给出明确建议（简单/复杂），用户确认后落盘；用户可显式指定 `--fast-track` / `--full` 覆盖建议。
- **daemon 快速路径派发**：`mode=fast-track` 的 spec 在 ready 后由单个 agent run（fast-track agent）在同一上下文完成实现 → 验证场景设计 → 场景验证 → 结果判定，状态机转换仍由 daemon 依据该 run 的统一结果文件推进（agent 不直接操作状态机）。
- **护栏保留并适配单 run**：零变更哨、交付物存在性守卫、fail 预算、token 预算在 fast-track run 上全部生效；run 内守卫替代 run 间守卫。
- **框架侧硬校验兜底**：fast-track run 的验证判定输出必须通过框架侧确定性校验（报告结构完整性、场景全量执行、证据存在性），agent 文本宣称不可作为通过依据。
- **bug run 内修复与升级路径**：验证发现 bug 时同一上下文内修复并重验（受 fix 预算约束）；预算耗尽自动升级为完整模式多 Agent 流水线继续处理，不静默丢弃。
- **Dashboard 模式标记**：spec 列表与详情页展示执行模式（fast-track / full）标记，便于人工辨识走的是哪条路径。

## Capabilities

### New Capabilities

- `fast-track-mode`: 快速路径运行时能力——mode 元数据驱动的单 Agent 全包执行路径（实现+场景设计+验证+判定同一上下文），含护栏适配、框架侧硬校验、run 内 bug 修复与超预算升级完整模式。
- `fast-track-mode-selection`: 模式选择能力——fenix-new 需求 Agent 的复杂度评估与建议流程、模式元数据写入约定、Dashboard 模式标记展示。

### Modified Capabilities

（无——`openspec/specs/` 下无活跃 spec，本变更全部为新增能力。）

## Impact

- **core/pm_engine/dispatch.py / engine.py**：新增 fast-track 派发分支与结果处理（升级完整模式的转换点）。
- **core/agent_runner/runner.py / prompt_builder.py**：新增 `run_fast_track` 与 fast-track 提示词模板（`agents/fast-track.md`），单 run 内完成四段工作并输出统一结果文件。
- **core/state_machine.py**：mode 元数据字段透传（无状态转换图变更，仅 entry 字段）。
- **core/verdict_check.py**：复用现有证据分类校验器，扩展对 fast-track 统一结果文件的确定性校验。
- **skills/fenix-new（项目源 + ~/.claude/skills 安装副本）**：新增模式评估建议流程与 `--fast-track` / `--full` 参数约定。
- **core/dashboard**：spec 列表/详情的模式标记。
- **worktree_manager**：fast-track run 全生命周期复用同一 worktree（实现、验证共用），成功后 merge 语义与完整模式一致。
