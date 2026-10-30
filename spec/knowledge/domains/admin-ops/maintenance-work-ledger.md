# 维护型工作登记台账

<!-- knowledge: capability=maintenance-work-ledger rev=1
     sources=spec/archive/2026-10-30-evo-maintenance-work-ledger -->

spec 全流程之外的延伸/维护型工作与散件经一行登记落账，从产生即有主、告警可归因、记账可见；登记型 run 以 `maintenance-` 前缀在 run 体系中识别为有名主体，不再落泛型「无主 agent」。

## 规则

- 台账是项目级文件 `.fenix/maintenance_log.jsonl`，逐行 JSON；读写由 `core/maintenance_ledger.py` 提供。STATE.md 准入语义不因登记扩展——其写者为全量重写语义、非 spec 记录会被丢弃，登记一律走台账独立文件。
- 登记条目字段：`ts`、`scope`（范围）、`actor`（执行者）、`evidence`（证据位置）、`note`，以及可选 `run_id`；`ts` 由写侧生成，`run_id` 缺省写 `None`。
- 追加接口在台账文件（含 `.fenix/` 目录）不存在时创建；连续追加逐行累积、不覆盖既有条目，读取保持落账顺序（旧→新）。
- 读取接口对坏行容错跳过（非法 JSON、JSON 数组顶层、裸字符串、空行），坏行不中断全量读取。
- 并发追加安全：执行者进程与 daemon 可并存并发写。单行超 `_ATOMIC_APPEND_LINE_BYTES=4096` 阈值走二进制单次 `os.write`，`O_APPEND` 下由内核对并发写者串行化、整行原子落盘，不产生半行 JSON 撕裂。
- 登记型 run id 形如 `maintenance-<scope>-<epoch 秒>`，由 `make_maintenance_run_id` 生成；`maintenance-` 前缀及类型映射登记于唯一真源表 `RUN_ID_AGENT_PREFIXES`（`core/agent_runner/run_files.py`），`admin_monitor` 的 `_RUN_PREFIXES` 消费表同步收录，新增前缀只改真源表。
- `maintenance-` run 在告警归因与盘点视图中还原为有名登记型主体；归一还原剥出的中段是 scope 而非真实 spec 名，无时间戳尾段的形态不强行归属，按真实 spec 名全等匹配的消费方（run_task_track、liveness 等）不会误命中。
- 台账条目经 `run_id` 字段与 maintenance- run 关联，`list_entries_for_run` 按 run_id 精确反查（告警归因→台账复盘的关联闭环）；无关联条目在全量读取中照常返回。
- 台账定位是「已登记但轻量」的记账事实，不是可派发任务：登记型 run 不派生实现/验证车道，登记入口的 CLI/dashboard 挂接属后续按需扩展。
- `core/agent_runner/maintenance_runs.py` 是运维 run（Administrator/每日自省/框架自进化）的宿主模块，与本台账无关，勿混淆。

## 溯源

- 2026-10-30 evo-maintenance-work-ledger（spec/archive/2026-10-30-evo-maintenance-work-ledger） — 新增维护型工作轻量登记台账能力：jsonl 台账读写与坏行容错、`maintenance-` 前缀两表收录、run_id 关联反查
