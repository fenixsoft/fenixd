# ADR-218：机器生成 HTML 产物经 iframe 沙箱（无 allow-same-origin）渲染

date: 2026-10-04
status: accepted

## Context

dashboard 开始下发 agent 生成的自包含交互式 HTML（archify 架构图；后续同类「生成可浏览产物」功能还会出现）。这类产物含脚本，渲染面等于在浏览器执行生成侧模板代码；dashboard 与框架服务同源，若直接内嵌或以同源 iframe 加载，主站 cookie、DOM 与本地存储全部暴露给生成内容——生成过程的提示注入可借此升级为对 dashboard 本体的攻击。

## Decision

机器生成的 HTML 产物一律经专用只读端点下发（Content-Type `text/html`，字节来自产物文件而非前端拼接）；前端渲染一律使用 `<iframe sandbox="allow-scripts">`，且 MUST NOT 授予 `allow-same-origin`——产物脚本只能跑交互逻辑，与主站存储、cookie、DOM 完全隔离。产物未就绪时端点返回结构化错误，前端不渲染空 iframe。容器布局用显式定高（视口高度减头部实测偏移，minHeight 兜底，移动端独立常数）防越界。

## Consequences

- 生成侧无论被注入什么指令，都无法读取主站 localStorage/cookie 或操作 dashboard DOM，危害被限制在沙箱内的产物交互。
- 跨源 iframe 内部 DOM 不可被外层脚本直接读取或断言：验证只覆盖端点契约与外层容器，前端逻辑不得依赖产物内部结构。
- 若未来出现必须同源交互的产物形态（读写主站数据），须作为独立安全设计重新评估，不得以顺手加 `allow-same-origin` 的方式放行。
