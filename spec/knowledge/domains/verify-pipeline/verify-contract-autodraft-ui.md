# 契约 AI 生成按钮
<!-- knowledge: capability=verify-contract-autodraft-ui rev=1 sources=spec/archive/2026-09-13-add-verify-contract-autodraft-ui -->

设置页验证契约卡片的人工触发入口：一键派发 Administrator 起草契约，覆盖既有契约须人类显式授权。

## 现行规则

- AI 自动生成入口：设置页验证契约卡片提供「AI 自动生成」按钮（操作区，与「插入模板」手动路径并列）；点击确认后异步派发 Administrator 起草请求并立即返回，不同步阻塞等待起草完成，也不发起任何对起草进度的轮询请求；编辑器保持可用，UI 提示拾取方式（admin 巡检周期内）与结果查看途径（运维记录 + 编辑器重新加载）。
- 覆盖须二次确认：契约缺失或解析失败时使用普通确认；契约存在且可解析（`load_verify_contract` 非 None）时弹出警示型确认（明示将覆盖现有内容与未保存编辑），用户取消不发出任何派发请求。
- 人类显式授权越界：用户在警示弹窗确认后请求携带 overwrite 意图，后端凭此派发——人类发起优先于「有效契约不碰」权限边界。
- 派发端点语义（`POST /api/verify-yaml-autodraft?project=<name>`）：未知项目 404 且不写任何信号；契约缺失/解析失败写 `verify_contract_missing` SIGNAL 并响应 dispatched；契约有效且无覆盖确认响应 skipped（附「契约已有效」文案）不写信号；契约有效且带覆盖确认写 `verify_contract_redraft` SIGNAL 并响应 dispatched。
- 手动信号可溯源：手动派发的 SIGNAL 记录标注 `source=ui-manual` 及 overwrite 意图，与验证链自动信号区分；手动触发无关联 spec，信号不强求 spec 字段且能被 admin_monitor 既有消费路径拾取。

## 溯源

- 2026-09-13 add-verify-contract-autodraft-ui（spec/archive/2026-09-13-add-verify-contract-autodraft-ui） — 新增设置页 AI 自动生成按钮、派发端点与覆盖授权语义：契约起草获得主动触发通道（原仅验证撞墙后的被动信号），覆盖有效契约由人类显式授权把守
