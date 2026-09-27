<!-- knowledge: capability=v2-admin-doc-modals rev=1 sources=spec/archive/2026-09-05-v2-admin-doc-modals -->

# v2 Admin 处置弹窗与 SPEC 文档弹窗

v2 列表页的两个入口弹窗：呼叫 Admin 接通 run 流 admin 状态机，「文档」入口懒加载三页签文档。

## 现行规则

- 两类弹窗经注册机制挂载；Escape 只关闭最上层弹窗。
- 列表行内「呼叫 Admin」打开 size lg 的 Dialog（body custom）：挂载 `window.RunStream.mount(mode=admin, project, spec)`，关闭时调 `dispose`；弹窗内可见等待态文案。
- SPEC 文档弹窗提供「需求背景 / 设计 / 任务清单」3 页签（mountOnEnter 懒加载），经 `GET /api/spec-doc?project=&spec=&doc=proposal|design|tasks` 取内容并渲染；文档未找到（404 或 `found:false`）时显示「未找到文档」，不报错白板。

## 溯源

- 史前复原 — v2 Admin 处置弹窗与 SPEC 文档弹窗经注册机制挂载，Escape 只关闭最上层弹窗
- 2026-09-05 v2-admin-doc-modals — Admin 弹窗接通 RunStream admin 状态机（等待态文案 + 关闭发出 DELETE watch 退订），文档弹窗落地三页签懒加载与「未找到文档」空态
