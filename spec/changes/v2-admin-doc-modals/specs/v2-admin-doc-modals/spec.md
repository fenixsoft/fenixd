## ADDED Requirements

### Requirement: Admin 处置弹窗接线

列表行内「呼叫 Admin」点击打开 size lg Dialog:body custom 调 window.RunStream.mount(mode=admin, project, spec),close 调 dispose;弹窗内可见等待态文案(behavior.md §4)。

#### Scenario: 打开进入等待态并清理
- **WHEN** 点击呼叫 Admin
- **THEN** Dialog 出现且显示等待态;关闭 Dialog 时 DELETE watch 被发出(page.route 拦截断言)

### Requirement: SPEC 文档弹窗

列表「文档」入口打开 Dialog:3 页签(需求背景/设计/任务清单)mountOnEnter 懒加载 GET /api/spec-doc?project=&spec=&doc=proposal|design|tasks;content 渲染;未找到(404 或 found:false)显示「未找到文档」。

#### Scenario: 有文档渲染
- **WHEN** 打开有文档的 SPEC 文档弹窗
- **THEN** 「需求背景」页签内容非空;切换页签按需加载

#### Scenario: 无文档分支
- **WHEN** 打开不在 STATE.md 的 spec 的文档弹窗
- **THEN** 显示「未找到文档」而非报错白板
