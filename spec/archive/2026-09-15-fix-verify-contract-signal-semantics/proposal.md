# fix-verify-contract-signal-semantics 变更提案

## Why

2026-09-08 UI 手动触发「AI 起草验证契约」产生 3 个假信号（契约已存在且有效仍发 `verify_contract_missing`），消耗 3 个 admin 自证 run 与一轮人工修复（b547eccb 已修自证工具 stop 顺序缺陷）。调查定案（2026-09-09）残余缺口有三：① 信号双载「真缺失」与「覆盖重起草」两种语义，契约有效时发出的 missing 信号语义即为假；② 前端确认后 100ms 竞态窗口内双击穿透，一次点击派发两个信号、两个串行 admin run 双倍烧钱（run2/run3 实证）；③ 服务端无幂等去重，重复触发全部落盘。

## What Changes

- **信号语义拆分（B）**：契约有效且用户确认覆盖时，端点改派 `verify_contract_redraft` 信号（保留 `source=ui-manual` 与 overwrite 标记）；`verify_contract_missing` 仅用于契约缺失/解析失败场景，不再被覆盖确认旁路。
- **admin 消费端注册新信号类型（B）**：`admin_monitor.py` 注册 `verify_contract_redraft` 的 severity 映射（major）、处置提示词（复核现有契约 → 有效时按用户授权重起草，或判定保留并说明理由）、STORED_SIGNAL_TYPES 注册与 evidence 项目名提取兼容。
- **服务端幂等去重（D）**：`POST /api/verify-yaml-autodraft` 派发前检查 AdminStore 是否已有同项目同 signal_type 的未消费信号（handled=false），存在则不重复写，响应 dispatched 并附在途提示。
- **前端触发防重入（D）**：`ProjectProfilePanel.tsx` 的 `handleAutodraft` 入口加同步 ref 锁，堵住 `setAutodraftLoading` 异步渲染前的双击穿透窗口。

## Capabilities

### New Capabilities

- `verify-contract-signal-dispatch`: verify.yaml 起草信号的语义拆分（missing/redraft 二分）与 admin_monitor 消费端注册
- `autodraft-dispatch-dedup`: UI 手动触发的幂等去重（服务端在途检查）与前端防重入锁

### Modified Capabilities

（无——`add-verify-contract-autodraft-ui` 的「派发端点语义」Requirement 行为由本变更新增的两个能力约束接替细化，原 change 已实现完毕待归档，不在此重复 delta。）

## Impact

- `core/dashboard/server.py`：`_api_verify_yaml_autodraft_post` 派发分支重构（信号类型二分 + 去重前置检查）
- `core/admin_monitor.py`：SIGNAL_SEVERITY / SIGNAL_RECOMMENDATION / STORED_SIGNAL_TYPES 三处注册 + `_detect_family_explosion` 的 spec 提取分支扩展
- `core/dashboard/static/src/pages/settings/components/ProjectProfilePanel.tsx`：`handleAutodraft` 加 useRef 同步锁
- `tests/test_dashboard_api.py`：既有 overwrite 派发测试断言更新为 redraft 类型 + 新增去重测试
- `tests/test_verify_contract_autodraft.py`：新增 redraft 信号消费测试
- 前端构建产物 dist 不入库，merge 后框架自动重建（声明 reference）
