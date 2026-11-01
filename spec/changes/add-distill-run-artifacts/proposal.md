## Why

指挥中心（command-center）组织网格的花名册没有 knowledge-distiller 车道，根因有两层：其一，蒸馏车道从不产出 run 产物——`DistillManager._spawn_once` 直接 `run_one_shot` spawn 裸 `claude -p`，不写 `.fenix/runs/*.jsonl`，而指挥中心 `aggregate_org` 只从 run 产物按 `agent_type` 聚合，永远观测不到蒸馏活动（连「其他」兜底分区都轮不到）；其二，`RUN_ID_AGENT_PREFIXES` 前缀真源与前端花名册（ROSTER / LANE_LABELS / LANE_ICONS）均未收录该车道。结果是：知识蒸馏作为唯一有配置面（设置页模型链）、有监督注册（WRAPUP_GRACE_AGENT_TYPES）、有失败台账的常驻车道，在指挥中心完全不可见。

## What Changes

- **蒸馏批次补 run 产物**：`DistillManager._run_batch` 批生命周期内创建并收尾一个 run 产物文件（`knowledge-distiller-<首归档名>-<时间戳>.jsonl`），批开始写 started 事件行、批收尾按结果写终态行（`result`/`error`）；写产物 fail-open（OSError 不阻断蒸馏主流程）。一批 = 一个 run（对齐「1 run = 1 车道派发」口径）。
- **run_id 前缀真源收录**：`RUN_ID_AGENT_PREFIXES` 新增 `("knowledge-distiller-", "knowledge-distiller")`，`infer_run_agent_type` / `run_spec_part` / `get_runs` 自动识别；消费方逐点核对（仿 arbiter- 先例）：`admin_monitor._RUN_PREFIXES` 不收录（蒸馏 spec 已归档，失败无活跃 spec 可还原，同 evo-/review- 口径）。
- **指挥中心花名册收编**：ROSTER 运营线增加 `knowledge-distiller`（蒸馏产出知识资产，归运营线）；前端 LANE_LABELS 补中文标签「知识蒸馏」、LANE_ICONS 补车道图标。
- **不做的事**：不改蒸馏 spawn 的 stdout 形态（保持裸文本，`output_format=None`）；run 产物不带 usage（`OneShotOutcome` 无 token 数据），命令中心成本/tokens 格显示缺失——stream-json 形态升级另立 SPEC，不在本轮范围。

## Capabilities

### New Capabilities
- `distill-run-artifacts`: 知识蒸馏车道的 run 产物观测契约——批生命周期产物写入、终态语义、fail-open 约束、run_id 前缀归属与消费面边界。

### Modified Capabilities
<!-- 无既有能力 spec 的 Requirement 变更：指挥中心聚合（add-command-center）与
     组织网格花名册的 Requirement 不改语义——knowledge-distiller 是新观测数据源
     进既有聚合管线；花名册常量扩员属实现层。归档目录已核查
     spec/archive/*/specs/ 无同族能力。 -->

## Impact

- **写侧**：`core/knowledge.py`（`_run_batch` 产物包装，唯一改动点，`_worker`/恢复重派路径经同一入口天然覆盖）。
- **前缀真源**：`core/agent_runner/run_files.py`（`RUN_ID_AGENT_PREFIXES` 追加一条）。
- **指挥中心**：`core/dashboard/data/command_center.py`（ROSTER 运营线扩员）；`core/dashboard/static/src/pages/command-center/shared.ts`（LANE_LABELS）；`core/dashboard/static/src/pages/command-center/OrgGrid.tsx`（LANE_ICONS）。
- **读侧零改动自动生效**：`get_runs` / `classify_run` / `runs_retention_check` / `aggregate_org` 均按既有契约消费新前缀产物（终态行进 `runs/archive/` 走「无主产物天龄兜底」清理，符合有界性）。
- **测试**：新增蒸馏产物单测；`tests/test_command_center_aggregation.py` 补蒸馏车道出卡场景。
- **风险面**：蒸馏车道在飞判定（`_distill_lane_busy`）读队列不读产物，不受影响；`pm_engine` 归属/取消/活动判定按活跃 spec 全等匹配，蒸馏 run 的 spec 段恒为已归档名，不新增误命中。
