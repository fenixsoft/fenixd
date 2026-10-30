# 设计：maintenance-work-ledger

## 根因

run 记账只有 spec 全流程形态，未识别前缀一律落泛型 agent；STATE 准入按 spec 生命周期设计，非 spec 记录会被下个写者移除。延伸/维护工作因此只能沿用旧 spec 名或完全游离。

## 方案

1. 新模块 core/maintenance_ledger.py：append_maintenance_entry(project, scope, actor, evidence, note, run_id=None) 追加一行 JSON 到项目 .fenix/maintenance_log.jsonl；list_maintenance_entries(project) 读取（坏行容错）。文件载体最小侵入，避开 STATE 准入改造。
2. core/agent_runner/run_files.py：RUN_ID_AGENT_PREFIXES（:32 起，定义处注释自述唯一真源、新增前缀只改这里）加 ("maintenance-", "maintenance") 映射。
3. core/admin_monitor.py：_RUN_PREFIXES（:570 起）同步 maintenance-，使告警归因把登记型 run 识别为有名主体。
4. 台账条目的 run_id 字段承载 R3 关联；登记入口后续按需挂 CLI/dashboard，不在本 SPEC。

## 关键取舍

- 独立 jsonl 而非 STATE.md 新节：STATE 写者是全量重写语义（_admit_entry 丢弃非 spec 条目），混入登记条目会被抹掉；独立文件零风险且可追加。
- 只加前缀识别、不建执行车道：台账型 run 是登记事实，不是可派发任务。
- 不动 core/agent_runner/maintenance_runs.py：该模块是运维 run（Administrator/每日自省/框架自进化）的拆分宿主，与本台账定位不同。

## 风险

- 台账无消费者时会退化为纯留痕：本 SPEC 先保前缀归因闭环（告警/盘点可见），消费视图后续按需扩展。
- jsonl 并发追加：落账是执行者自助（执行者进程与 daemon 可并存并发写），并非「单进程顺序写」——实现沿用 run_files.py:78-85 的成文约定（_ATOMIC_APPEND_LINE_BYTES=4096：行超阈值走二进制单次 os.write，O_APPEND 下由内核对并发写者串行化、整行原子落盘；先例 code-review item 29df176ff441：TextIOWrapper 长行会裂成多次 raw write、与并发写者交错产生半行 JSON 被读侧跳过）。台账单行登记通常远小于阈值，仍按同一约定实现，不复踩半行交错。
- 全量前缀表消费方核对（仿 evo-add-run-metrics-lane-baseline 先例，run_files.py:26-52 内联记录）：maintenance- 与既有 14 个前缀无子串冲突（顺序不敏感）；.fenix/runs 无存量 maintenance- run（2026-10-08 实测 0 条），无追溯重解析影响；dashboard data.py:get_runs 消费全量表，登记型 run 自动归入有名主体；run_spec_part 剥出的中段为 scope（非真实 spec 名），run_task_track/liveness 等按真实 spec 名匹配的消费方不会误命中（同 evo- 裸 epoch 段先例，全等守卫不变）；pm_engine 归属/取消/活动判定不新增命中。