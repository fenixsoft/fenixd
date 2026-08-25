# Tasks: 运行记录弹窗改用 FlowToken 渲染

## 1. FlowToken 打包与静态接入

- [x] 1.1 在临时构建目录 `npm install @nvq/flowtoken react react-dom` + esbuild，将入口打包为 IIFE：优先将 react/react-dom 标记 external 复用现有 `window.React`/`window.FenixReactDOM` 全局（不可行则自包含打包、独立 React root 挂载），输出 `vendor/flowtoken.bundle.js` 暴露 `window.FlowToken = { AnimatedMarkdown }`，并将 FlowToken 的 `dist/styles.css` 输出为 `vendor/flowtoken.bundle.css`
- [x] 1.2 在 `core/dashboard/static/index.html` 引入 `flowtoken.bundle.js`（在 `fenix.bundle.js` 之后）与 `flowtoken.bundle.css`
- [x] 1.3 验证静态可达：`GET /vendor/flowtoken.bundle.js` / `.css` 返回 200；`node --check` 校验 bundle 语法；页面加载 `window.FlowToken` 定义且无 console error

## 2. 运行记录弹窗重写

- [x] 2.1 新增 `RunView` React 组件（或等价渲染函数）：接收 events/status/error props，复用 `collapseThinkingTokens` 折叠；assistant/user/result 文本经 `AnimatedMarkdown content=... animation={null}` 渲染；tool_use / tool_result / error / stderr / system 以结构化 React 元素渲染（延续现有 `runEventMd` 语义与 `.run-event` 视觉）
- [x] 2.2 改造 `renderRunModalBody` / `renderRunModalBodyLive`：弹窗 body 由字符串拼接改为 React root 挂载/更新（打开时 `createRoot`，关闭时 `unmount`；运行中轮询更新 props）；保留弹窗骨架、`runmodal-title`、滚动容器；状态转换弹窗 body 保持现状
- [x] 2.3 在 `core/dashboard/static/style.css` 补充 FlowToken 容器（markdown/prose 排版、代码块、等宽事件元素）样式，沿用现有颜色变量与设计语言

## 3. 测试与验证

- [x] 3.1 `node --check` 校验 `flowtoken.bundle.js` 与 `app.js` 语法；`python3 -m pytest tests/ -q` 全量通过，无回归
- [x] 3.2 端到端验证（重启 dashboard 后）：打开运行记录弹窗确认静态 Markdown 无重放动画、工具调用/结果/错误终态可见、运行中弹窗随新事件更新且滚动保持、状态转换弹窗与时间轴入口不回归、控制台无 FlowToken 报错
