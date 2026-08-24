# Design: 并行度设置与严格优先级并行调度

## Context

当前调度（`core/pm_engine.py`）：

- `_run_queue`：`(spec_name, agent_type)` 的 FIFO 列表。
- `_process_queue`：每次被调用（事件处理尾、worker 结束 finally）时，检查 `_active_runs >= max_concurrent`（`agents.max_concurrent`，默认 2），从队首 `pop(0)` 取出条目，校验 SPEC 状态（implementer 需 `ready`、verifier 需 `implemented`），转换状态后启动 worker 线程。
- `_enqueue` 追加队尾；`_enqueue_front` 插入队首（用于 implementer 成功后 verifier 紧跟）。
- SPEC 的 `priority`（`STATE.md`，默认 5；fix SPEC 为 `min(parent+1,10)`）**仅用于报告排序**，不参与派发。

问题：FIFO + 并发上限导致低优先级任务可能占满槽位，高优先级任务饥饿等待；priority 形同虚设。

目标（用户已确认）：
1. 并行度 = 复用 `agents.max_concurrent`。
2. 严格优先级并行：高优先级先执行；同优先级并行至并行度上限；不同优先级不并行（低优先级等高优先级全部完成后才启动）。
3. 并行度纳入 Dashboard 配置页可视化编辑（与 llm/审批模式一致，重启生效）。

## Goals / Non-Goals

**Goals:**
- 派发按 SPEC priority 严格串行分档，档内并行。
- 复用 `agents.max_concurrent` 作为并行度，不新增配置键。
- Dashboard 配置页可视化编辑并行度。
- 向后兼容：未显式配置时行为不劣于现状（FIFO+上限），旧配置无需改动。

**Non-Goals:**
- 不实现任务抢占（已在运行的 Agent 不因更高优先级到达而被 kill/中断）。
- 不重排已在运行的 Agent。
- 不改变 priority 的产生规则（fix = parent+1 等保持现状）。
- 不做配置热加载（与既有约定一致，重启生效）。

## Decisions

### D1: 队列条目携带 priority，按优先级分档派发

`_run_queue` 条目改为 `(priority, spec_name, agent_type)`，priority 在 `_enqueue`/`_enqueue_front` 时从 `STATE.md` 读取（缺省 5）。`_process_queue` 派发算法（严格优先级并行）：

```
每轮派发（有空闲槽位时）：
  active_prios  = 当前正在运行条目的 priority 集合
                 （不变量：严格调度下至多含一个值）
  queued_valid  = 队列中状态合法的条目（implementer→ready、verifier→implemented）
  queued_best   = min(queued_valid 的 priority)，队列空则 None

  若 active_prios 非空：
      active_prio = active_prios 中唯一值
      若 queued_best != active_prio:
          # 有其它优先级任务在运行/等待 → 不派发新档位（严格不并行、不抢占）
          本轮不派发，返回
      否则 target = active_prio   # 同一优先级，允许并排补齐至并行度
  否则:
      target = queued_best        # 无运行任务，启动当前最高优先级档

  从 queued_valid 中取出所有 priority == target 的条目，
  在 _active_runs < max_concurrent 约束下逐个派发（每派发一个占用一个槽位）。
```

- **不变量**：任何时刻所有正在运行的 Agent 都属于同一 priority 档；新档位只在前一档全部排空后才启动。
- **高优先级先执行**：高优先级（priority 数值小）任务入队后，只要无其它档位正在运行即立即派发；若有低优先级档正在运行，则等其排空（不抢占），排空后高优先级档先行。
- **同优先级并行**：同一档内多个任务按队列顺序填充空闲槽位至 `max_concurrent`。
- **低优先级不占位**：只要队列或运行中存在更高优先级档，低优先级任务绝不会被派发。

- **替代方案**：队列整体按 priority 排序 + 并行度内混跑 —— 被用户否决（选择严格优先级，不同优先级不并行）。
- **替代方案**：priority queue / heap —— 语义等价，但列表 + 每轮扫描已足够（队列规模 = 就绪 SPEC 数，量级小），改动最小。

### D2: `_enqueue_front` 语义改为「同档优先」，不再依赖物理位置

现状 `_enqueue_front` 把 verifier 插到队首，使其紧跟对应 implementer。优先级调度下「队首」不再有意义。改为：`_enqueue_front` 仍是「插入」，但保持队列按 priority 排序的稳定性——verifier 与它的 implementer 属于同一 SPEC、同一 priority，插入后自然落回同一档。实现上：

- `_enqueue`（队尾）与 `_enqueue_front`（队首）都写入 `(priority, spec, agent)`。
- `_process_queue` 派发时对同一 `target` 档内的条目，**保持原始入队顺序**（verifier 紧跟 implementer 的相对顺序通过档内 FCFS 保留），保证验证顺序与现状一致。

- **理由**：保留「implementer 完成 → verifier 优先」的相对顺序（档内 FCFS），仅将「物理队首」替换为「同一优先级档内的先到先服务」，避免验证顺序回退（见风险）。

### D3: 并行度复用 `agents.max_concurrent`，Dashboard 配置页扩展受管键

- 不新增配置键；`agents.max_concurrent`（默认 2，已由 `ConfigLoader._validate` 校验为正整数）即并行度。
- `config.template.yaml` 中 `max_concurrent` 注释更新为「并行度：同时运行的 Agent 进程数上限；同优先级任务可并行至该值」。
- `core/dashboard/data.py` 的 `read_config`/`write_config` 受管键由 `llm`、`agents.models`、`gates.approve_mode` 扩展至 `agents.max_concurrent`；复用现有 `GET/POST /api/config` 端点与配置页，前端新增一个并行度数字输入。
- **注**：现有 `write_config` 刻意只管理 `agents.models` 子键以避免覆盖 `max_concurrent`（data.py:826 注释）；本次将 `max_concurrent` 显式纳入受管键，需在合并逻辑中保证其它 `agents` 子键（如 `subagent_model`、`max_retries`）仍原样保留。

### D4: 向后兼容

- 旧 `.fenix/config.yaml` 无任何改动要求：`agents.max_concurrent` 早已存在且被读取。
- 未显式设置并行度时默认 2，行为从「FIFO 上限 2」变为「严格优先级档内并行上限 2」——并发上限不变，仅派发顺序改为优先级感知，属预期行为变更（feature 本身）。
- 所有 SPEC priority 相同（如全默认 5）时，调度退化为「档内 FCFS 并行至上限」，与现状 FIFO+上限等价。

## Risks / Trade-offs

- [验证顺序回退] → D2 档内 FCFS 保留 implementer→verifier 相对顺序；补充回归测试断言「同 SPEC 的 verifier 紧随其 implementer 之后派发」。
- [严格串行导致并行度空置]（如仅 1 个高优先级任务时低优先级不补位）→ 用户明确选择严格语义；文档与配置页注释说明「低优先级任务需等高优先级全部完成」，避免误读。
- [正在运行的低优先级档阻塞高优先级启动] → 无抢占是现实约束（kill 运行中 Agent 有副作用）；高优先级档在低优先级排空后立即启动，且低优先级不会新增启动。文档注明不抢占。
- [Dashboard 写配置覆盖其它 agents 子键] → D3 合并逻辑显式白名单受管键，写回前保留 `subagent_model`/`max_retries` 等；单元测试覆盖「写并行度后其它 agents 键不变」。
- [并发线程竞争（多个 worker 同时 _process_queue）] → 沿用现有 `_queue_lock`；派发判定与槽位占用在锁内原子完成，priority 扫描同样在锁内。

## Migration Plan

1. 实现 `pm_engine` 队列结构与 `_process_queue` 优先级派发；`_enqueue`/`_enqueue_front` 携带 priority。
2. 扩展 `core/dashboard/data.py` 受管键与配置页前端（并行度输入）。
3. 更新 `config.template.yaml` 注释。
4. 单元测试（派发算法 + 配置合并 + 回归顺序），运行 `python3 -m pytest tests/ -q` 全绿。
5. 端到端：真实启动多 SPEC（不同/相同 priority）观察派发顺序与并行度；Dashboard 修改并行度重启后生效。

## Open Questions

- 是否需要把「当前派发档位」暴露到 Dashboard（如展示正在并行运行的 SPEC 及 priority）——本 SPEC 不做，属后续增强。
- 高优先级任务等待低优先级档排空的最大等待时间是否需要告警（blocker 检测已有 stuck 阈值兜底，暂不加新机制）。
