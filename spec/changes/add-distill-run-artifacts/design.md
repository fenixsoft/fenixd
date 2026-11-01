# Design: add-distill-run-artifacts

## Context

知识蒸馏车道（`core/knowledge.py` DistillManager）是 fenixd 唯一「有配置面、有监督注册、有失败台账，却在指挥中心完全不可见」的常驻车道。不可见的根因是双层的：

1. **数据源缺失（根本）**：`_spawn_once`（knowledge.py:1795）经 `run_one_shot` spawn 裸 `claude -p`（`output_format=None` 压掉 stream-json 缺省），全程不写 `.fenix/runs/*.jsonl`。指挥中心 `aggregate_org` 只从 run 产物按 `agent_type` 聚合（command_center.py:530），蒸馏活动对观测链完全透明。
2. **花名册缺员（表层）**：`RUN_ID_AGENT_PREFIXES`（run_files.py:33 唯一真源）、ROSTER（command_center.py:57）、前端 LANE_LABELS / LANE_ICONS 均未收录 `knowledge-distiller`。

既有观测契约的四个锚点（本设计全部复用、不新造）：

- run_id 前缀 → agent_type 归属：`infer_run_agent_type`（run_files.py，顺序敏感首命中）；
- status 终态判定：`classify_run` 读产物末行 `type`，查 `_RUN_TERMINAL_STATUS_MAP`（`result`→done / `error`→error，runs.py:344）；
- started/duration：首行事件 `timestamp` 优先，回退 run_id 内嵌 `-<9-10位Unix秒>`；duration 优先 run_metrics 指标日志、回退 mtime 推算；
- 产物生命周期：daemon 周期保留清理 `runs_retention_check` 把终态产物移入 `runs/archive/`；无主产物（不归属活跃 SPEC）按天龄兜底删除。

## Goals / Non-Goals

**Goals**

- 蒸馏批次产出符合既有读侧契约的 run 产物，指挥中心聚合管线零改动自动亮卡。
- 前缀真源 + 花名册 + 前端标签/图标三处收编，卡片落在运营线正名出卡。
- 全链 fail-open：产物写失败绝不影响蒸馏主流程（蒸馏的正确性优先级恒高于观测）。

**Non-Goals**

- 不改蒸馏 spawn 的 stdout 形态（保持裸文本）：`OneShotOutcome` 无 usage 数据，run 产物不带 token/cost，卡片成本格显示缺失。stream-json 形态升级（可带来真实 usage）价值独立、风险面不同（stdout 诊断摘要语义变化），另立 SPEC。
- 不给蒸馏 run 补 run_metrics 指标日志行：`_log_lane_run_metrics` 依赖 `AgentRunner` 实例（`runner._log_run_metrics` 咽喉），DistillManager 是独立线程无 runner；duration 回退 mtime 推算已够卡片用时显示。
- 不动 `admin_monitor._RUN_PREFIXES`、`pm_engine` 归属判定、`_distill_lane_busy` 在飞口径（见 Decisions D3 消费面核对）。

## Decisions

### D1：合成产物形态（写侧自控事件行），不改 spawn 传输形态

蒸馏产物 = DistillManager 在批生命周期内写入的合成事件流，spawn 的 stdout/stderr 保持裸文本。

- **备选 A（否决）**：spawn 改 `--output-format stream-json` 落 run 文件，与实现车道完全同构，还能白拿 usage。否决理由：蒸馏失败诊断依赖 stdout 尾部摘要（`_spawn_once` 失败路径把 stdout_tail 写进日志与 todo.md 台账 reason，code-review 0d6683c2b68d 教训），stream-json 化后诊断摘要变 JSON 噪声，需连带改造诊断读取路径；且 `run_one_shot` 的 stdout 契约、ENV_MODE_CLEAN 清洁环境声明都要重验——改动面与风险远超「观测可见性」这一目标。列为后续升级路径。
- **备选 B（采纳）**：批开始 `touch` + 写带 `timestamp` 的开始行，批收尾按 `result` dict 写 `result`/`error` 终态行。`classify_run` 只读末行 type，合成行与原生行在读侧完全等价；蒸馏主链路零侵入。

**写点**：`_run_batch`（knowledge.py:1650）是批的唯一生命周期入口（`_worker` 与 pending 台账恢复重派路径都汇聚于此），在函数体内 try/finally 包装——进入建文件+写开始行；`finally` 按 `result["ok"]`/`result["error"]` 写终态行。四个 return 路径（成功/失败 give_up/提交失败滞留/校验违规放弃）由 finally 统一收口，不逐点插桩。

**一批 = 一个 run**：对齐「1 run = 1 车道派发」口径（run 计数语义单源）。批内多轮修正 spawn（`1 + _max_fix_rounds` 轮）不另开产物——修正轮是同一派发的内部重试，与实现车道 attempt 复用同 run_id 基座的语义对齐。批内全归档名单写进开始行 `archived` 字段数组，run_id 中段取首归档名（人类可读溯源；`run_spec_part` 剥段结果非活跃 spec 名，全等守卫天然不命中）。

**run_id 形态**：`knowledge-distiller-<首归档名>-<int(time.time())>`。归档名自带日期前缀（如 `2026-10-31-add-command-center`，含点号）——run_id 白名单 `_RUN_ID_RE`（`[A-Za-z0-9._-]`）允许点号，合法；尾部 `-<ts>` 段被 `strip_run_id_suffixes` 正常剥除。并发安全：DistillManager 每项目单 worker 线程逐批消费（`_worker` 循环），单写者无交错；退避撞秒概率趋零且撞名仅影响溯源可读性，不做去重后缀。

### D2：fail-open 三道防线

1. 文件创建/事件行追加全部 try/except OSError 吞掉（与 runner.py:2059 `run_file.touch` 既有防御口径一致）；
2. 终态行写在 finally 内，但 finally 自身不抛——写失败静默放弃产物，蒸馏 result 照常返回；
3. 产物半成品（daemon 中途 SIGKILL 断尾）由读侧既有 stale 兜底（末行非终态 + mtime 停更 1800s → stale）——`RUN_TIMEOUT_SECONDS = 1800` 超时 killpg 后终态行照写，正常路径无 stale 窗口。

### D3：消费面逐点核对（仿 arbiter- 先例 bc3c07e8 纪律）

| 消费方 | 核对结论 | 动作 |
|---|---|---|
| `get_runs` / `run_spec_part` | 消费 `RUN_ID_AGENT_PREFIXES` 真源，前缀收录即自动工作 | 无改动，单测锁定 |
| `admin_monitor._RUN_PREFIXES` | 蒸馏 spec 已归档，失败计数无活跃 spec 可还原（同 evo-/review- 口径） | **不收录** |
| `admin_monitor._is_admin_run_id` / 处置者判定 | knowledge-distiller 非处置族 | 无改动 |
| `pm_engine` 归属/取消/活动判定 | 按活跃 spec 全等匹配；蒸馏 spec 段恒为已归档名 | 不新增误命中，单测锁定 |
| `_distill_lane_busy`（fenixd.py:1938） | 读队列+线程，不读产物 | 保持不变 |
| `runs_retention_check` | 终态产物移 archive/ 后走「无主产物天龄兜底」删除 | 符合有界性，无改动 |
| WRAPUP_GRACE_AGENT_TYPES（runner.py:462） | 蒸馏已注册，无 runner 实例路径不受产物影响 | 无改动 |

### D4：花名册收编位置——运营线

蒸馏的输入是归档 SPEC、产出是 `spec/knowledge/` 知识资产页，本质是知识资产运营而非质量裁决（不重跑不判死刑），归运营线（administrator/evolution 同区）。备选质量线（judge 同区，因蒸馏有校验违规修正环）否决：校验环是产出合格性门，不是对交付物的裁决，语义不等价。

前端同步三件：`LANE_LABELS['knowledge-distiller'] = '知识蒸馏'`；`LANE_ICONS['knowledge-distiller'] = BookOutlined`（蒸馏产出知识页，语义贴切，@ant-design/icons 6.3.2 已核实存在）；ROSTER 运营线追加 lane（零 run 编制内出卡 Requirement 自动保证空卡可见）。

### D5：usage 缺失的显示口径

命令中心 `_run_cost_and_tokens`（command_center.py:243）对无 usage 的 run 返回 `(None, None)`——既有「不可计价显示缺失」口径直接覆盖蒸馏 run，零改动。卡片聚合按 None 透传，MUST NOT 伪显 0（与分母口径的既有纪律一致：缺数据不冒充零样本）。

## Risks / Trade-offs

- **[蒸馏 run 无成本/token 数据，指挥中心成本合计低估] → 接受并声明**：蒸馏低频（归档触发），缺失显示优于伪 0；stream-json 升级路径已在 Non-Goals 立项接口。
- **[合成产物与原生产物流形差异误导排障（如按产物 tail 查蒸馏过程）] → 缓解**：开始行带 `archived` 全名单与 `rounds` 字段，终态 error 行带 reason 摘要；产物行数随修正轮增长，排障看 reason 与 todo.md 台账双源。
- **[前缀收录触发未知读侧隐式消费] → D3 表逐点核对 + 单测锁定边界两侧**（归属正确 + admin/pm 不误命中），仿 arbiter- 先例的核查义务清单落 tasks。
- **[花名册扩员改变既有卡片布局密度] → 低风险**：运营线 2→3 卡，组织网格分区布局已有 3+ 卡先例（交付线 3 卡），无新布局形态。
- **[蒸馏在飞时产物末行非终态被监督面当普通在飞 run] → 核对过**：recovery watch / liveness 按 runner 监督注册表工作，蒸馏 run 文件不在注册表，仅读侧 get_runs 可见（working 判定正确亮灯，恰为本 SPEC 目标）。

## Migration Plan

纯增量交付，无迁移：新产物只对新蒸馏批次产生，存量无产物形态不受影响；回滚 = revert 写侧包装（产物停止新增，已落盘产物由 retention 天龄兜底自然清理）。

## Open Questions

无——写点、形态、边界、显示口径均已在侦察中定案。
