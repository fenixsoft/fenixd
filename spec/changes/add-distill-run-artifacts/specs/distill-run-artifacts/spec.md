## ADDED Requirements

### Requirement: 蒸馏批次产出 run 产物

知识蒸馏车道（DistillManager）的每个批次 MUST 产出恰好一个 run 产物文件，路径 `.fenix/runs/knowledge-distiller-<首归档名>-<Unix秒>.jsonl`（一批 = 一个 run，对齐「1 run = 1 车道派发」口径；一批多归档时 run_id 中段取首归档名，批内全名单记录在事件行字段）。产物 MUST 满足：

- 批开始（首个 spawn 前）创建文件并写入一条带 `timestamp` 的开始事件行；
- 批收尾（`_run_batch` 每个 return 路径）追加恰一条终态事件行：批结果 `ok=True` 写 `result`，其余（run 失败/校验违规放弃/提交失败滞留）写 `error`（附 reason 摘要）；
- 产物写侧 MUST fail-open：任何 OSError（目录不可写、磁盘满等）MUST NOT 阻断蒸馏主流程，蒸馏结果与台账行为与无产物形态完全一致。

#### Scenario: 批成功产物落盘

- **WHEN** 一个蒸馏批次（含归档 `spec/archive/2026-10-31-add-command-center`）经修正轮后校验通过并成功提交
- **THEN** `.fenix/runs/` 下存在 `knowledge-distiller-2026-10-31-add-command-center-<ts>.jsonl`，首行为带 `timestamp` 的开始事件行，末行 `type=result`，文件行数随修正轮数递增但不改变终态判定

#### Scenario: 批失败写 error 终态

- **WHEN** 蒸馏 spawn 非零退出（如网关拒识模型名）触发 `_give_up` 放弃产出
- **THEN** 同一批次的产物末行 `type=error` 且携带失败原因摘要，`classify_run` 判定为 `error`

#### Scenario: 产物写失败不阻断蒸馏

- **WHEN** `.fenix/runs/` 目录不可写（产物创建/追加抛 OSError）
- **THEN** 蒸馏批次的 spawn、校验、提交、台账（pending/todo.md）行为与产物写成功形态完全一致，无异常外泄

### Requirement: run_id 前缀归属与消费面边界

`RUN_ID_AGENT_PREFIXES`（run_files.py 唯一真源）MUST 收录 `("knowledge-distiller-", "knowledge-distiller")`，使 `infer_run_agent_type` / `run_spec_part` / `get_runs` 对蒸馏产物自动归属 `agent_type=knowledge-distiller`。消费面边界（逐点核对义务，仿 arbiter- 先例）：

- `admin_monitor._RUN_PREFIXES` MUST NOT 收录该前缀（蒸馏 spec 已归档，失败计数无活跃 spec 可还原，同 evo-/review- 口径）；
- `pm_engine` 归属/取消/活动判定按活跃 spec 全等匹配，蒸馏 run 的 spec 段恒为已归档名，MUST 不新增误命中；
- 蒸馏车道在飞判定（`_distill_lane_busy`）MUST 保持读队列口径，不消费 run 产物。
- `aggregate_org` 的「已归档 SPEC 名下 run 全窗剔除」过滤（command_center.py 归档剔除）MUST NOT 命中蒸馏产物：剔除按 `.fenix/STATE.archive.md` 清单键（原始 SPEC 名，无日期前缀）全等匹配，蒸馏 run 的 spec 段为归档目录名（带日期前缀），形态错位天然不命中——该形态耦合由单测锁定，run_id 中段命名形态变化时 MUST 同步复核本条。

#### Scenario: get_runs 归属正确

- **WHEN** `.fenix/runs/` 存在 `knowledge-distiller-2026-10-31-add-command-center-1793xxxxx.jsonl` 且末行为终态
- **THEN** `get_runs` 返回该行 `agent_type="knowledge-distiller"`、`spec="2026-10-31-add-command-center"`（`run_spec_part` 剥前缀与时间戳段）、status 为终态映射值

#### Scenario: 不还原到活跃 spec 失败计数

- **WHEN** 蒸馏产物为 error 终态
- **THEN** `admin_monitor` 失败/spec 还原路径不消费该产物（前缀不在 `_RUN_PREFIXES`），活跃 spec 的失败计数不受影响

#### Scenario: 在飞判定不受产物影响

- **WHEN** 蒸馏批次在飞（产物末行非终态）但队列已空（批已出队进入 spawn）
- **THEN** `_distill_lane_busy` 返回值与无产物形态一致（按队列+线程判定），不因产物存在而改变

#### Scenario: 归档剔除过滤不吞蒸馏 run

- **WHEN** `.fenix/STATE.archive.md` 清单已含本批首归档 SPEC 名（原始名形态，如 `add-command-center`）且今日窗口内存在 done 终态蒸馏产物（spec 段为带日期前缀的归档目录名，如 `2026-10-31-add-command-center`）
- **THEN** `aggregate_org` 运营线蒸馏卡 runs 计 1——归档剔除过滤以清单键全等匹配，形态错位不命中剔除集

### Requirement: 指挥中心花名册收编知识蒸馏车道

指挥中心组织网格 ROSTER（command_center.py 唯一真源）MUST 在运营线收录 `knowledge-distiller`，使蒸馏 run 经既有 `aggregate_org` 聚合自动出卡（零聚合代码改动）。前端 MUST 同步：`LANE_LABELS` 补 `knowledge-distiller → 知识蒸馏` 中文标签；`LANE_ICONS` 补车道图标（花名册内车道不得落 `FileUnknownOutlined` 兜底）。run 产物不带 usage 时，卡片成本/tokens 格 MUST 显示缺失（None 透传），MUST NOT 伪显示 0。

#### Scenario: 蒸馏 run 入窗出卡

- **WHEN** 今日窗口内存在一条 done 终态的 knowledge-distiller 产物
- **THEN** `aggregate_org` 运营线出现 `lane=knowledge-distiller` 卡片：runs 计 1、success_rate 分母含该 run、zone=运营线；时间窗「今日/7 日/全量」三档口径一致

#### Scenario: 中文标签与图标出卡

- **WHEN** 组织网格渲染含 knowledge-distiller 卡
- **THEN** 卡主标题显示「知识蒸馏」（非原样英文 lane 名），图标为 LANE_ICONS 登记组件（非 FileUnknownOutlined 兜底）

#### Scenario: 零 run 编制内出卡

- **WHEN** 窗口内无任何蒸馏 run 产物
- **THEN** 运营线仍出「知识蒸馏」卡（花名册编制内车道零 run 也出卡的既有 Requirement），runs=0、working=false

#### Scenario: 成本缺失不伪显 0

- **WHEN** 蒸馏产物无 usage 数据（裸 stdout 形态）
- **THEN** 卡片成本/tokens 聚合按 None 透传显示缺失，与其他车道「不可计价显示缺失」口径一致
