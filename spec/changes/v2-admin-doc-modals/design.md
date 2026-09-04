## Context

admin 状态机已在 run-stream 组件内实现(v2-run-stream-modal),本 SPEC 只是 Dialog 接线(计划 Task 9 Step 3 JSON 逐字)。spec-doc 端点语义(behavior.md §1):返回 {found, content};对不在 STATE.md 的 spec 返回 404 而非 found:false——错误分支语义不同,adaptor 需区分处理。真实 admin invoke 会触发框架行为,测试降级为等待态出现 + 关闭退订(page.route 拦截)。

## Goals / Non-Goals

- Goals: 呼叫 Admin → admin 弹窗全链路;文档弹窗三页签懒加载与 404 分支
- Non-Goals: admin 状态机内部逻辑(已属 run-stream SPEC)

## Decisions

- **Dialog 接线复用 run-stream 契约**:body custom onMount 调 mount(mode=admin),close 调 dispose(计划 Task 9 Step 3 逐字)
- **文档页签懒加载**:tabs mountOnEnter + unmountOnExit false(打开过的页签保持,避免重复请求);service adaptor 把 404/未命中映射为「未找到文档」展示
- **测试不真触发 admin**(会呼叫框架 agent):等待态文案断言 + route 拦截断言清理

## Risks / Trade-offs

- admin invoke 的 409 分支难以在测试中稳定制造,以 run-stream SPEC 的单测逻辑为准,此处仅接线冒烟
