# Design: improve-v3-spec-doc-markdown

## Context

- v3 文档弹窗已存在（`pages/projects/list.tsx` 内联 state + `<pre>` 纯文本），端点 `GET /api/spec-doc` 返回 `{found, content}`。
- 运行时入口（验证场景导航用）：v3 前端为 `http://localhost:8787/v3/dist/index.html#/projects/<project>`；8787 根路径是 v1/v2 界面而非 v3，`/api/spec-doc` 端点在 8787 同源下。
- v1 文档弹窗（`app.js` docmodal ~2031-2120 行）语义基线：三页签、docCache（loading/done/empty/error 四态）、mdRender（vendored marked，GFM + 链接协议白名单）。

## Goals / Non-Goals

- Goals：v3 文档弹窗 Markdown 渲染 + 页签级缓存 + 三态完备。
- Non-Goals：不做文档编辑；不做 Markdown 导出；不迁移 v1 的 mdRender 自定义渲染器细节（按 v3 技术栈重新实现等价安全语义）。

## Decisions

- **D1 渲染库**：`react-markdown` + `remark-gfm`（React 生态标准、声明式、与 React 19 兼容），链接白名单通过自定义 `components.a` 实现（非白名单协议渲染为纯文本）。若实现方论证更优方案（如 marked + DOMPurify）须满足 spec 的安全 Scenario。
- **D2 组件抽离**：文档弹窗从 `list.tsx` 抽为独立组件 `src/pages/projects/components/SpecDocModal.tsx`（props: project, spec, open, onClose），内部持有 tab 状态与缓存 Map；spec 列表页只负责开关。
- **D3 缓存**：`Map<`${spec}:${doc}`, {status: 'loading'|'done'|'empty'|'error', content?}>` 组件级缓存；弹窗关闭不清缓存（对齐 v1），切换 spec 时缓存键含 spec 天然隔离。
- **D4 加载态**：Loading 态渲染 Spin；empty 渲染 Empty（"无此文档"）；error 渲染错误 Alert + 重试按钮。

## Risks / Trade-offs

- react-markdown 对任务勾选（task list）渲染为只读复选样式，不可交互——与 v1 一致（v1 亦为静态渲染）。
- 大文档渲染性能：tasks.md 通常数百行，react-markdown 足够；不做虚拟化。

## Migration Plan

依赖安装 → 组件抽离 → Markdown 渲染 + 白名单 → 缓存与三态 → 浏览器走查（对照 v1 弹窗同 spec 同页签内容一致）。

## Open Questions

- 无。
