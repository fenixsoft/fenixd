# Proposal: 并行度设置与严格优先级并行调度

## Why

当前 Fenixd 的 Agent 派发（`pm_engine._process_queue`）使用 FIFO 队列，仅靠 `agents.max_concurrent`（默认 2）限制并发进程数，**完全不参考 SPEC 的 priority**。后果：低优先级任务可能先入队并占满并发槽位，高优先级任务却在排队等待，优先级形同虚设。用户希望：

1. 有明确的「并行度」设置（复用现有 `agents.max_concurrent`），决定最多同时开多少个 Agent 进程。
2. 调度按优先级进行：高优先级任务先执行；**同一优先级内的任务允许并行执行**（至并行度上限）；不同优先级的任务不并行（低优先级等高优先级全部完成后才启动）。

并行度设置需与既有配置体系一致：写入 `.fenix/config.yaml`（手工可改），并在 Dashboard 配置页可视化编辑。

## What Changes

- **并行度即 `agents.max_concurrent`**：复用现有配置键（默认 2），明确其含义为「并行度」——同时运行的 Agent 进程数上限；模板注释与配置校验同步说明。
- **严格优先级并行调度**：改造 `pm_engine` 的派发队列与 `_process_queue` 逻辑：
  - 队列条目携带 SPEC priority（`STATE.md` 的 `priority`，默认 5）。
  - 每次派发取「当前就绪的最高优先级档」，该档内多个任务可并行至 `max_concurrent` 上限。
  - 不同优先级不并行：当有其它优先级的 Agent 正在运行时，不派发新优先级档的任务（严格串行切换）；低优先级任务不因「并行度有空位」而被提前启动。
  - 高优先级任务到达时，不抢占已在运行的 Agent，但新派发只面向最高优先级档。
- **`_enqueue_front` 语义适配**：verifier 紧跟 implementer 的「插队」在优先级调度下改为按同一优先级排队（携带所属 SPEC 的 priority），不再依赖队列物理位置。
- **Dashboard 配置页接入**：在现有「配置」页新增并行度设置（`agents.max_concurrent`）可视化编辑，与 llm / 审批模式一致地写入 `.fenix/config.yaml`（重启 daemon 生效）。
- **模板同步**：`config.template.yaml` 中 `agents.max_concurrent` 注释更新为「并行度」，并补充优先级调度说明。

## Capabilities

### New Capabilities

- `parallelism-config`: 并行度配置项（复用 `agents.max_concurrent`）的语义界定、校验与模板同步；Dashboard 配置页可视化编辑并行度。
- `priority-parallel-scheduler`: 严格优先级并行调度——高优先级先执行、同优先级并行至并行度上限、不同优先级不并行、向后兼容（未配置时行为等价于现状 FIFO+并发上限）。

### Modified Capabilities

<!-- 现有 openspec/specs/ 与归档目录均无已定义能力，本次全部为新增。 -->

## Impact

- **核心代码**：
  - `core/pm_engine.py`：`_run_queue` 条目结构（携带 priority）、`_enqueue` / `_enqueue_front` 改按 priority 入队、`_process_queue` 改为优先级感知派发（读取各排队/运行条目的 priority 决定派发档位）。
  - `core/config.py`：`agents.max_concurrent` 校验保持（正数），注释/语义更新；无新配置键。
  - `core/dashboard/data.py`：配置页受管键扩展至 `agents.max_concurrent`（`read_config` / `write_config`）。
  - `core/dashboard/server.py` / `static/`：配置页新增并行度输入，复用现有 `GET/POST /api/config` 端点（无需新端点）。
  - `config.template.yaml`：`agents.max_concurrent` 注释更新。
- **行为**：调度从 FIFO 变为严格优先级并行；SPEC priority 首次真正参与派发。
- **测试**：`tests/test_core.py` 增加优先级派发（高优先级先执行、同优先级并行、不同优先级不并行、并行度上限、向后兼容）单元测试。
- **回归风险**：`_enqueue_front` 的「verifier 紧跟 implementer」语义变化——由优先级保证（verifier 与 implementer 同 priority，属于同一档），需验证不引入验证顺序回退。
