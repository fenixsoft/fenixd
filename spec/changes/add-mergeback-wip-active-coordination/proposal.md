# 提案：add-mergeback-wip-active-coordination

## Why

合回被主树 WIP overlap 挡住后，当前只能被动轮询等待主树 WIP 自然清除：2026-09-24 实测一批等了 47 分钟（占用者是并行 SPEC 实现车道在改 `CodeFixProgressCard.tsx`），且框架不知道占用者是谁——是「在飞车道正常工作」还是「陈旧无主 WIP」全靠人猜，后者同样静默等待。

## What Changes

- **ADDED** 占用者识别：overlap 文件集与在飞实现车道（implementer/code-fix run 的分支与交付物改动集）求交，判定「在飞持有者」或「无主陈旧 WIP」
- **ADDED** 事件驱动合回重试：持有者为在飞车道时，订阅其 run 终态事件即时重试合回，替换固定长间隔轮询作为主要唤醒手段（轮询降级为兜底）
- **ADDED** 无主升级：判定为无主陈旧 WIP 时，在可配置宽限（缺省 30min）后升级既有 `mergeback_wip_overlap` 人工告警（admin major 已有分级），MUST NOT 无限期静默等待
- 既有 WIP overlap precheck 拦截语义与主树零污染保证不变（本 SPEC 只治理「等待」维度）

## Capabilities

### New Capabilities

- `mergeback-wip-active-coordination`: 合回 WIP overlap 的占用者识别、事件驱动重试与无主升级

### Modified Capabilities

（无——`evo-add-codefix-batch-wip-precheck`（precheck 本体）与 `evo-add-wip-defer-merge-retry-consumer`（defer 消费者）的既有 requirement 不变，本 SPEC 是其等待策略的增强）

## Impact

- `core/worktree_manager/`（overlap 检测与延迟合回路径）
- `core/code_fix.py`（defer 批合回消费者的唤醒来源）
- `core/admin_monitor.py`（复用既有 `mergeback_wip_overlap` 信号，新增无主升级触发点）
- 事件来源为 run 终态（run 文件终态事件行 / runner 终态收口）；per-run 监听注册为本 SPEC 新增（现状无通用订阅 API，见 design D2）；`scheduling_kick` 不作为唯一唤醒（单槽位 conflict 静默丢弃缺陷，见 design D3）
