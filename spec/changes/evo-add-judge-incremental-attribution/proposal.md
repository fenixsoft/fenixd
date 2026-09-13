## Why

planner-judge 一次性输出全部场景归因，批量归因查重门只能整批判定「通过/废弃」——单轮被判废时整轮 token 废弃，且重跑仍有再产出模板化归因的风险。fenix-server 实证（fenixd.log 15:53:16Z 23 场景 / 16:39:41Z 5 场景整批拒绝，add-web-ui）：planner-judge-add-web-ui-1789056218-a1 单轮 cost=$11.16 被整体废弃（run 文件 total_cost_usd 读取确认），同窗口还有多条 $10+ 单笔。若归因逐场景增量落盘，拒绝仅回炉重复子集，单次浪费从整轮（10M token 级）降为子集级。

## What Changes

- planner-judge 归因按场景增量写盘：每场景归因独立落一条目（同一产物文件内按场景条目组织，或独立文件），记录场景 id / 归因文本 / 状态。
- 批量归因查重拒绝改为场景级：拒绝时按重复子集回炉，已通过场景归因保留复用，不清空整轮。
- 保留 n-gram 查重语义不变（仅粒度从整批降为单场景）；无 dashboard UI、无新配置键。

## Capabilities

### New Capabilities
- `judge-incremental-attribution`: judge 归因逐场景增量写盘 + 查重拒绝场景级回炉

### Modified Capabilities
批量归因查重（既有）粒度细化：整批判定 → 场景级判定。

## Impact

- **core/pm_engine/verification.py**（或 judge 产物落盘模块）：归因写盘按场景组织；查重拒绝按场景子集回炉。
- **core/verify_engine/**（如读取归因的路径）：读侧兼容新增结构。
- **tests/**：场景级拒绝子集回炉 + 已通过场景复用断言。