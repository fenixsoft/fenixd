# 提案：verify.yaml 编辑器「AI 自动生成」按钮（verify-contract-autodraft-ui）

## Why

add-verify-contract-autodraft 机制落地后，契约起草的唯一触发通道是验证撞墙后的被动信号。人类在 Dashboard 看到项目没有契约（或契约失效）时，没有任何主动入口点一下就让 AI 起草——只能等验证失败或自己手写。设置页 verify.yaml 编辑器是这一操作的自然位置（旁边就是「插入模板」手动路径）。

## What Changes

- 设置页「项目简介」面板的验证契约卡片新增**「AI 自动生成」按钮**（操作区，「插入模板」旁）。
- 后端新增 `POST /api/verify-yaml-autodraft?project=<name>`：契约缺失/解析失败 → 经 `AdminStore` 写 `verify_contract_missing` SIGNAL（`source=ui-manual`，携带 overwrite 意图标记）派发 Administrator 起草；契约有效且用户未确认覆盖 → 响应 `skipped` 不派发（权限边界「有效契约不碰」在 UI 侧把守）。
- 覆盖授权语义：已有有效契约时按钮弹**警示型**确认（覆盖现有内容含未保存编辑）；用户确认 = 人类显式授权，请求携带 overwrite，可越过「有效契约不碰」边界（人类发起优先于边界）。
- **异步不轮询**：起草是 admin agent run（分钟级），按钮点击即返回，UI 提示拾取方式（admin 巡检周期内）与结果查看途径（运维记录 + 编辑器「重新加载」）。

## Capabilities

### New Capabilities
- `verify-contract-autodraft-ui`: 验证契约 AI 起草的人工触发入口——设置页按钮 + 派发端点 + 覆盖授权语义。

### Modified Capabilities

（无——父能力 verify-contract-autodraft 尚在 add-verify-contract-autodraft change 中实现、未归档为活跃能力 spec；本 change 与其文件触点零重叠。）

## Impact

- `core/dashboard/server.py`：新增派发端点（复用现有 verify-yaml 端点的项目解析）
- `core/dashboard/static/src/services/dashboard.ts`：新增 API 客户端
- `core/dashboard/static/src/pages/settings/components/ProjectProfilePanel.tsx`：新增按钮与确认交互
- `core/admin_monitor.py`：确认/适配手动信号（无 spec 字段）的消费路径
- `tests/test_dashboard_api.py`：端点五场景单测
