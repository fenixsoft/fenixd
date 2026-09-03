## Why

Dashboard 项目视图 SPEC 列表的文档列与信息行有三处体验问题：

1. **信息行浪费纵向空间**：信息子行中「信息」标签与消息内容之间存在一个换行（信息子行 `white-space: pre-wrap` 保留了源码中标签与内容间的换行符），一条短消息被拉成两行。
2. **信息无法手动清理**：`STATE.md` 的 `error` 字段被 Agent 或恢复流程写入后（如 `Recovered from interrupted state`），信息行会一直显示，用户无法在界面上清除已过期的提示。
3. **文档入口分散**：「背景」「设计」两个按钮各开一个独立弹窗，用户想完整了解一个 SPEC 需分别点击两次；任务清单（tasks.md）在列表页根本没有文档入口。

## What Changes

- **信息标签与内容同行**：信息子行中「信息」badge 与消息正文渲染在同一行、之间无换行，仅消息内容自身换行时按文本内换行处理。
- **信息行新增「清除」按钮**：信息子行行尾提供清除按钮，点击后调用新端点 `POST /api/spec-error-clear`，将该 SPEC 的 `error` 字段置空并原子写回 `STATE.md`；watcher 感知 STATE.md 变化后推送刷新，信息子行随即消失。清除仅作用于当前快照，Agent 后续若重新写入则再次显示。
- **文档列整合为单个链接 + 三页签弹窗**：文档列由「背景」「设计」两个按钮整合为一个「文档」超链接，点击弹出单窗口，内含「需求背景 / 详细设计 / 任务清单」三个页签，分别对应 `proposal.md`、`design.md`、`tasks.md` 原文的 Markdown 渲染。页签内容按需加载（首次激活才请求），各页签缺失时展示各自空态文案。后端 `GET /api/spec-doc` 的 `doc` 白名单由 `{proposal, design}` 扩展为 `{proposal, design, tasks}`。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities
- `spec-doc-view`: SPEC 文档读取端点变化 —— `doc` 白名单由 `{proposal, design}` 扩展为 `{proposal, design, tasks}`（`tasks.md` 与 `proposal.md` 同目录，读取路径与校验逻辑一致）。
- `dashboard-spec-table`: SPEC 列表表格行为变化 ——「背景」「设计」两个按钮整合为单个「文档」链接并打开三页签弹窗；「信息」标签与内容同行显示；信息子行尾部新增「清除」按钮（配套新增 `POST /api/spec-error-clear` 端点）。

## Impact

- **前端**：`core/dashboard/static/app.js`（`specRow` 文档列与信息子行渲染、`openDocModal` 重构为三页签、新增清除按钮交互与端点调用）；`core/dashboard/static/style.css`（信息行布局修复、文档链接样式、弹窗页签样式）；`core/dashboard/static/index.html`（docmodal 增加页签容器）。
- **服务端/API**：`core/dashboard/data.py`（`_SPEC_DOC_WHITELIST` 扩展、新增 `clear_spec_error` 写回函数）；`core/dashboard/server.py`（新增 `POST /api/spec-error-clear` 路由，复用 `StateMachine.update_spec` 的 flock 原子写）。
- **测试**：`tests/test_dashboard.py`（`doc=readme` 400 用例不变、新增 `doc=tasks` 读取用例；新增清除端点用例：spec 不存在 404、非法项目 404、成功后 STATE.md `error` 置空）。
- **行为边界**：清除不改变 SPEC 状态机其余字段（status/priority 等），仅置空 `error`；文档弹窗页签互不阻塞，加载失败显示错误态而非空白。