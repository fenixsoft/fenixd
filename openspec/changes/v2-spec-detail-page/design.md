## Context

API 字段权威 behavior.md §1(含 verdict.summary 计数可能是字符串 "0" 的坑,adaptSpecDetail 已数字化);SSE detail 帧带 spec 名,仅与当前路由参数一致才刷新(behavior.md §0)。截图路径 /screenshots/<project>/<spec>/<file>(server.py 防穿越)。

## Goals / Non-Goals

- Goals: 4 页签渲染真实数据;时间轴节点可点击打开弹窗(契约就绪);detail 帧定向刷新
- Non-Goals: 运行记录弹窗内容(Task 8);文档弹窗(Task 9)

## Decisions

- **detail 帧比对**:onEvent sse:detail 的 custom script 比对 `event.data.spec === window.V2.route().params[1]`,不一致不刷新(计划 Task 7 Step 3)
- **时间轴用 AMIS timeline**(形态可变):source=${timeline},节点渲染由 behavior.md §1 字段落笔
- **截图**:grid + image(thumbMode cover),点击放大用 AMIS image 内建 preview

## Risks / Trade-offs

- 时间轴节点点击事件在 AMIS timeline 的动作绑定方式需实测;若节点级 onEvent 不可用,退路是节点 title 渲染为链接 tpl + 整体点击处理(以测试通过为准)
