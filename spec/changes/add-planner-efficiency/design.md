# Design — Planner 提效三件套

## Context

2026-09-05 转录分析定案：planner 单轮 30-70 分钟零产出 = 大轮次任务（54-148 次工具调用，prompt 硬约束「navigate 路径须源码证据+文件:行号出处」所致）× 网关长尾延迟（deepseek-v4-flash 经 inferaiapi.com，中位 1-10s 但 ~25% 轮撞 60-185s 停顿，双峰与轮次位置无关=缓存未命中/网关排队）。成功对照轮（interrupt-recovery 77 轮 28 分钟）同款画像——不是卡死是慢。三个杠杆：减轮次（②）、降并发互挤（③）、让长尾可见（④）。

约束：框架通用性铁律——框架不解析被测应用源码，地图生成器由项目声明；存量项目零迁移（无生成器/无配置=现状）；告警降噪铁律（可观测数据≠告警源）。

## Goals / Non-Goals

**Goals**
- planner 出题轮次显著下降（地图注入替代大部分源码考古）
- planner 并发对网关的压力可由用户调节（设置页开关，注解说清取舍）
- 每个 run 的 API 延迟画像可检索（在线摘要 + 失败证据 + 历史追溯）

**Non-Goals**
- 不做 dashboard run 详情页延迟直方图渲染（后续可选增强）
- 不做延迟独立告警/admin 自动唤起
- 不改动派发层 `agents.max_concurrent` / `parallelism-config` / `priority-parallel-scheduler` 语义
- 不引入 prompt cache 优化或模型路由变更（另一话题）

## Decisions

### D1 路由地图：生成时机与落点（②）

- **生成点**：`core/pm_engine/verification.py` 阶段1 进入处、`run_planner` 调用前（`verification.py:846` 附近）。此处 impl worktree 已就绪（worktree_manager 建/复用完成）。
- **来源=impl worktree**（非主树）：impl 分支 merge 回 main 为 fast-forward，worktree 内容=被测形态；spec 新增路由只在 impl 分支上，主树地图会瞎。地图写 `<worktree>/.fenix/route-map.md`（worktree 私有，并行验证互不污染，随 worktree 清理消亡）。
- **复用键=worktree HEAD**：HEAD 未变（replan 循环/重验）跳过生成器；HEAD 变更重生成。与 impl worktree 复用语义同键。
- **生成器协议**：项目根 `bin/gen-route-map.py`，框架以 worktree 为 cwd、单参（worktree 根）调用，stdout 为人类可读 Markdown（含条目+`文件:行号`出处），超时 60s，非零退出/超时=失败 fail-open。框架不解释生成器内部。
- **静态地图兼容**：主树 `.fenix/route-map.md` 作为无生成器项目的替代源；优先级 worktree 生成 > 主树静态 > 无。
- **prompt 注入**：`prompt_builder.py` `_project_extra_section`（:183）新增 route-map 段；措辞模板钉死「已知入口索引、非穷尽清单；spec 涉及但地图未覆盖的入口仍须自行源码取证」——防线在措辞（生成器覆盖不全时 planner 不放弃取证）。
- **生成器自检**：dashboard 参考实现内置宽 grep 启发式计数 vs 解析条目数比对，差 ≥30% 输出 warning（防解析模式漏配）。

### D2 planner 节流：信号量位置与开关（③）

- **信号量在 `agent_runner.run_planner` 入口**（而非 verification.py 调用处）——run_planner 是全部 planner 路径（完整管线+fast-track+重排）的单一咽喉，一处包裹全覆盖；取消/异常路径经 try/finally 释放，不泄漏。
- **配置键 `verify.planner_max_concurrent`**：0/缺省=不节流（现状）；正整数=跨管线上限。模块级 `threading.BoundedSemaphore`，按配置惰性重建（配置热更新生效）。
- **UI**：`ParallelSettingsPanel.tsx` 新增「planner 生成节流」Switch（默认关）+ 上限 InputNumber（默认 1，1-10）；注解文案三点：限什么（全框架同时在出题的 planner 数）/为什么（多 planner 同打网关时降低长尾停顿概率）/代价（验证吞吐下降，排队 spec 等待更久）。配置读写走 `services/dashboard.ts` 既有 settings 通道。
- **recovery 相容**：节流等待发生在 verifier 槽**已派发**之后——recovery watch 的 dispatch_stalled 判据（ready/implemented 无活跃派发）与 stuck 判据（testing 无 run 进度）均以 run 产物为证据，等待期 run 未结束不产生「无进度」误判；防御性补一条：排队等待开始时打 INFO 日志（spec 名+等待序位），时间轴可审计。风险窗口=等待超过 stuck 阈值（160min）且 run 文件无写入——实测 planner run 文件持续增长（1s 级事件流），等待中的 run 无事件写入理论上可能触 stuck 判定， Scenario 覆盖此形态：等待期 run 记录「throttled-wait」事件保活（实现取其一即可，验收以「不误报」为准）。

### D3 延迟直方图：纯读侧（④）

- **在线**：`runner.py` `_run_claude` 流式循环（:1732）旁路记录——last_event_ts 与当前事件 ts 差值，「tool_result → assistant」样本入列；run 退出路径（成功/异常/取消）统一打摘要日志（component=agent_runner，含 run_id）。复用 `_parse_event_timestamp`（:1928）。
- **失败证据**：run 失败分支把摘要行拼入 error 上下文（与 fix-admin-disposition-empty-shell 的失败可见性同型）。
- **事后**：`bin/analyze_run_latency.py`——与在线同口径解析 run jsonl（复用同一解析函数，从 runner.py import 或抽公共模块），支持 glob 批量、按 p90 排序、损坏文件跳过。
- **不做告警**：摘要只进日志；不写 admin_alerts、不触发 Administrator。

## Risks / Trade-offs

- 地图生成器覆盖不全 → 靠 prompt 措辞兜底（planner 不放弃地图外取证）+ 生成器自检告警；地图错误条目可能浪费 planner 数轮抽查——可接受（远小于全量考古）
- 节流开启降低验证吞吐 → 默认关，注解说清，用户知情选择
- 等待期 stuck 误判残余窗口 → 「不误报」Scenario 验收 + 保活事件方案备选
- run 转录 timestamp 缺失的旧文件 → 统计跳过该样本，摘要标注样本数

## Migration Plan

存量项目零迁移：无生成器→无地图（planner 现状）；无配置→不节流；runner 统计对旧转录只读。dashboard 自带 `bin/gen-route-map.py` 作为首个消费方（自举：fenixd 自己的 planner 先受益）。

## Open Questions

（无——生成时机/来源/措辞/开关位置均已与用户对齐；延迟数据口径=tool_result→assistant 间隔，与 2026-09-05 事故分析口径一致。）
