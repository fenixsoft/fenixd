<!-- knowledge: capability=v2-spec-detail-page rev=1 sources=spec/archive/2026-09-05-v2-spec-detail-page -->

# v2 SPEC 详情页

v2 的 SPEC 详情：验证卡 + 4 页签 + SSE 定向刷新 + 时间轴节点接入运行记录弹窗。

## 现行规则

- `#/spec/:project/:name` 渲染验证结论卡（verdict 计数已数字化）、验证进度、任务清单 + 4 页签：时间轴（timeline，source=${timeline}）、场景结果（table）、Bug（table）、截图（image 网格，src=/screenshots/...，点击放大预览）。
- 验证卡标题恒可见。
- SSE 刷新：spec-detail 监听 `sse:detail` 仅当帧内 spec 名与当前路由 params[1] 一致才 reload；监听 `sse:state` 无条件 reload；其它 SPEC 的 detail 帧不触发重拉。
- 时间轴节点点击打开 size lg 的「运行记录」Dialog（body custom：onMount 调 `window.RunStream.mount`，mode=run，runId 来自节点数据）；Dialog close 事件调 `dispose`。

## 溯源

- 史前复原 — v2 详情页验证卡 + 4 页签 + SSE detail 刷新骨架；验证卡标题恒可见
- [2026-09-05 v2-spec-detail-page](spec/archive/2026-09-05-v2-spec-detail-page/) — 落地验证结论卡数字化、4 页签内容区（时间轴 / 场景 / Bug / 截图 lightbox）、sse:detail 定向刷新与时间轴节点弹窗契约（RunStream run 模式挂载 + dispose 清理）
