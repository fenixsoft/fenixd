# 任务清单：verify.yaml 编辑器「AI 自动生成」按钮（verify-contract-autodraft-ui）

## Deliverables

```yaml
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/ProjectProfilePanel.tsx
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
```

## 1. 后端派发端点

- [x] 1.1 `core/dashboard/server.py` 新增 `POST /api/verify-yaml-autodraft?project=<name>`：项目解析复用现有 verify-yaml 端点路径（未知项目 404）；`load_verify_contract` 轻量判定——契约缺失/解析失败写 `verify_contract_missing` SIGNAL（`AdminStore.append`，`source=ui-manual`、请求带覆盖确认时携带 overwrite 标记，spec 字段留空、项目名入 evidence）响应 dispatched；契约有效且无 overwrite 响应 skipped（附「契约已有效」文案）不写信号；有效且带 overwrite 照常派发
- [x] 1.2 `core/admin_monitor.py` 验证手动信号（spec 字段为空 + source=ui-manual）被既有「未 escalated 记录 → 唤起 Administrator」通用路径拾取且受同源信号节流约束；若存在 spec 字段强依赖则补最小容缺适配（预期不改消费主路径）
- [x] 1.3 `tests/test_dashboard_api.py` 端点单测五场景：未知项目 404；契约缺失 → dispatched + 信号落盘含 source 标注；契约有效无 overwrite → skipped 且零信号；契约有效带 overwrite → dispatched；信号记录字段完整性（signal_type/source/overwrite/evidence 项目名）

## 2. 前端按钮与交互

- [x] 2.1 `core/dashboard/static/src/services/dashboard.ts` 新增 `autodraftVerifyYaml(project, overwrite)` API 客户端（POST，携带覆盖意图）
- [x] 2.2 `ProjectProfilePanel.tsx` 验证契约卡片操作区（「插入模板」旁）新增「AI 自动生成」按钮：契约缺失/解析失败态走普通 Popconfirm（文案：探索项目 → 生成契约 → 三段自证 → 提交仓库，约数分钟）；契约有效态走警示 Popconfirm（明示覆盖现有内容与未保存编辑），取消不发请求；派发成功 message 指引拾取周期/运维记录/重新加载，失败 message.error；按钮 loading 态防连点
- [x] 2.3 前端回归：无契约/有契约两态下按钮与弹窗行为正确（data-testid 命名与既有 verify-yaml-* 系列一致），dashboard 构建通过
