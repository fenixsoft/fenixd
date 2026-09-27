# ADR-008：Dashboard 零新增依赖技术栈

date: 2026-09-02
status: accepted

## Context

Dashboard 须随框架一键安装（install.sh 自动接入），安装面要求零额外依赖；运行环境为离线本机 localhost，无 CDN 可用。技术栈选型是约束后续所有 Dashboard 能力的前提裁定。

## Decision

- 服务端：Python 标准库 `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`，提供 REST JSON API 与静态资源服务；项目依赖保持零额外 pip 包（既有仅 PyYAML）。
- 前端：无构建、无 CDN 的原生 HTML/CSS/JS 单页应用；Markdown 渲染使用 vendored 的 marked（随库分发，不运行时安装、不引外部脚本）。
- 需要系统能力时以标准库替代第三方包（如进程探测遍历 `/proc` 而非引入 psutil）。
- 主题/样式体系用原生 CSS 变量实现，不引入 CSS 框架或预处理器。
- 新的 Dashboard 能力默认在既有栈内实现；引入任何 pip/前端依赖都须作为显式架构变更裁决，不得随单个功能顺手带入。

## Consequences

- 安装即用、离线可用、无构建链维护成本；多项目监控、配置编辑、文档查看等全部能力均在此栈内落地。
- 代价是复杂交互（图表、虚拟滚动等）须手写实现，规模化前端能力的天花板受栈约束。
- vendored 资源随库升级须手工同步，存在版本滞后风险。
