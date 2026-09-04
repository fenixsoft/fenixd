# Proposal: add-spec-context-menu

## Why

Fenix Web Dashboard 的 spec 列表目前只有「文档」链接与「信息清除」按钮，用户遇到卡死/异常的 SPEC 时缺乏就地处置手段：呼叫 admin 只能等 daemon 的 admin_monitor 30 分钟一轮自动检测或人工敲命令；调整优先级与删除 SPEC 均需直接编辑 STATE.md 或跑脚本。spec 列表是用户注视最频繁的界面，需要一个统一的右键菜单承载这三个高频运维动作。

## What Changes

- spec 列表的每个 spec 行支持浏览器右键弹出上下文菜单（自绘 DOM 菜单，拦截原生菜单），含三项：
  1. **呼叫 Admin 介入**：POST 触发 daemon 立即拉起 Administrator Agent，发送固定检查指令（检查该 SPEC 出现什么问题）；已存在进行中的 admin run 时拒绝并提示
  2. **调整优先级**：弹窗输入 1-9 数字（P1 最高），写入 STATE.md priority 字段
  3. **删除 Spec**：软删除——STATE.md 移除该条目 + `openspec/changes/<name>/` 目录移入 `openspec/changes/archive/<name>-<时间戳>/`；带确认弹窗；归档目录不参与扫描可恢复
- Dashboard server 新增三个 POST API（仿 spec-error-clear 先例）：
  - `POST /api/spec-admin-invoke?project=<name>&spec=<name>`
  - `POST /api/spec-priority?project=<name>&spec=<name>`（body: priority）
  - `POST /api/spec-delete?project=<name>&spec=<name>`
- daemon 主循环新增文件信号拾取：`.fenix/admin_invoke_request.json` 存在时立即唤起 Administrator（固定指令模板），处理完即删
- 右键菜单对 done/verified/bug-found 状态同样可用（删除语义对任意状态生效）

## Capabilities

### add-spec-context-menu

spec 行右键菜单 UI 与三项动作的前端交互、确认弹窗、错误反馈。

### add-spec-manual-admin-invoke

手动唤起 Administrator 的端到端通路：dashboard API → 文件信号 → daemon 拾取 → agent_runner.run_administrator（自定义 signal_type=manual-intervention）→ 处置结果照常落 admin_alerts/admin_disposition。

### add-spec-priority-and-delete-api

优先级写回与软删除的后端实现：priority 校验(1-9)后 update_spec；删除=STATE.md 剔除条目 + spec 目录移入 archive 归档区（带时间戳防同名冲突），可手工恢复。

## Impact

- 受影响代码：
  - `core/dashboard/static/app.js`（右键菜单组件、弹窗、fetch 调用）
  - `core/dashboard/static/style.css`（菜单样式）
  - `core/dashboard/server.py`（3 个 POST handler）
  - `core/dashboard/data.py`（priority 更新、软删除的 STATE.md 操作与目录移动）
  - `core/fenixd.py`（主循环增加 admin_invoke_request 拾取）
  - `core/agent_runner.py`（run_administrator 支持外部信号复用，无需改签名）
  - `core/state_machine.py`（新增 remove_spec 方法）
- 不改变现有 admin_monitor 自动检测逻辑，二者共存（节流各走各的 store 锚点）
- 风险：手动唤起可能被滥用导致 LLM token 消耗——通过「同 spec 进行中拒绝重复唤起」缓解
