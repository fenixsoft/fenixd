# Proposal: add-arbiter-quality-display

## Why

add-arbiter-lane（2026-10-31）上线后，arbiter 车道在两处界面以「无名氏」形态出现：指挥中心组织网格中 arbiter 作为花名册外观测 lane 单独出卡在「其他」分区，与质量线的 judge 卡（质量裁决）并存，用户无法把两者对应起来；SPEC 运行时间轴中 arbiter run 节点因前端标签映射缺条目而显示为「未知 Agent」，且 arbiter 真正做了什么（自主处置还是升级人工、根因是什么）在时间轴上不可见——处置台账虽有富结构，但没有任何界面消费它。

## What Changes

- 指挥中心组织网格：观测 lane 归并表 `LANE_ALIASES` 新增 `arbiter → judge`，arbiter 的 run 计数/成本/在飞归属并入 judge 卡统一显示为「质量裁决」，不再单独出「其他」卡；spec 视图轮次聚合同口径归并（同表消费，自动一致）
- SPEC 运行时间轴：前端 Agent 标签单源（`runVisual.ts` 的 `AGENT_LABEL` / `RUN_ID_PREFIX_LABEL`）补 arbiter 条目「质量裁决 Agent」，消除「未知 Agent」
- SPEC 运行时间轴富展示：后端时间轴 run 节点按 run_id 联查 arbiter 处置台账（`.fenix/arbiter_ledger.jsonl`），命中 `disposition`（自主处置）/`escalation`（升级人工）条目时在节点上附带处置结论与根因摘要；前端 run 节点卡片渲染该块；台账文件缺失或未命中时静默省略（fail-open，对齐 `lane_summary` 既有模式）
- daemon 重启信号：后端聚合层/时间轴为 daemon 内存代码，合并后需 supervisor 消费 `restart_request` 重启加载

## Capabilities

### New Capabilities

- `timeline-arbiter-visibility`: SPEC 运行时间轴中 arbiter run 节点的可见性与处理记录富展示（标签修正 + 台账联查渲染）

### Modified Capabilities

- `command-center-aggregation`: 组织网格数据派生的观测 lane 归并口径变化——`LANE_ALIASES` 新增 `arbiter → judge`（需求 1 的后端单点；既有 `dispute-judge → judge`、`repair → code-fix` 同族扩展，时间线/拓扑屏保持原生 agent_type 的既有定稿口径不变）

> 能力全集检索记录（2026-11-01）：活跃 `spec/changes/add-command-center-spec-view/specs/`（command-center-aggregation、command-center-console-ui）与归档 `spec/archive/`（含 2026-10-31-add-command-center、2026-09-27-add-timeline-ocr-lane-visibility 等）均已检索；无既有「时间轴 arbiter 可见性」能力，组织网格归并为既有能力口径修改。
