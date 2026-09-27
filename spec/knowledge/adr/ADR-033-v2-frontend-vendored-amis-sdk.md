# ADR-033：v2 前端栈 = vendored AMIS SDK + JSON DSL 页面

date: 2026-09-04
status: accepted

## Context

dashboard 前端能力增长后，原生手写复杂交互成本高（ADR-008 已预见天花板）。运行环境为离线内网，CDN 不可用；引入 npm/node 构建链与 node_modules 则与零维护成本目标冲突。前端栈换代需要一次显式架构裁决。

## Decision

- 前端渲染层切换到 AMIS SDK（JSON DSL）：SDK 产物 vendored 落盘随库分发——vendor 而非 CDN，离线可用优先；以 tarball 提取而非 npm install，不引入构建链、不污染 node_modules；仅取运行必需文件，版本锁定，升级须重跑 vendor 流程。
- 页面以独立 JSON 文件承载，加载期按 url 前缀深合并进 app schema（构建期合并、带防缓存参数）；单页缺失时跳过不阻塞——页面可由后续 SPEC 并行增量交付，互不阻塞。
- app 组件壳统一承载侧边导航、参数路由与页面按需渲染；路由用 hash 模式，兼容既有 `#/` 链接形态；SSE 桥等横切能力挂壳级。
- 本条修订 ADR-008 的前端形态（原生 JS 单页 → AMIS SDK JSON DSL）；ADR-008 的零构建、vendored、离线优先与「新依赖须显式架构变更裁决」原则继续有效，本条即依该条款作出的显式裁决。

## Consequences

- 复杂界面以 JSON 声明交付，页面并行扩展无构建冲突、无前端手写成本；代价是 SDK 数 MB 入仓（一次性 vendor，已接受）。
- SDK 模式下字符串形式的 schema/onMount 执行语义需实测，退路是在宿主侧全局注册自定义渲染器；行为回归以行为基准文档为准。
