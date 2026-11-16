# ADR-361：dashboard 剪贴板写入单源助手与非安全上下文降级硬要求

date: 2026-11-16
status: accepted

## Context

dashboard 经 frp 隧道以公网纯 HTTP（home.icyfenix.cn:18787）对外提供访问，该形态非 secure context，`navigator.clipboard` 整体缺失；直连 127.0.0.1 的本机自检环境无法复现该缺口，降级路径缺失只在公网端暴露。剪贴板写入类交互（复制 SPEC 名称等就近取用）若直接消费 `navigator.clipboard.writeText`，公网访问者必然失败；若各交互各自实现 textarea/execCommand 降级，则节点清理、异常吞噬、transient activation 手势窗口等降级细节散落多点多代漂移。

## Decision

dashboard 前端剪贴板写入唯一单源助手 `copyToClipboard`（`src/components/claude-msg/Markdown.tsx`，已导出）：`navigator.clipboard.writeText` 首选，异常 fall through 隐藏 textarea + `execCommand('copy')` 降级（含节点 finally 清理）。所有剪贴板写入类交互必须复用导入、禁自写剪贴板实现；非安全上下文降级是硬要求而非可选项——新增复制交互必须在公网纯 HTTP 访问下照常可用，且在用户手势的同步回调链首行即调（满足 transient activation 窗口），写入失败如实提示不误报成功。单源纪律以源码扫描测试钉死（消费文件禁出现 execCommand/textarea 自写剪贴板代码）。

## Consequences

公网 HTTP 访问下复制交互零缺口，降级语义单点演进全量受益；代价是助手成为关键路径单点（其缺陷影响所有复制交互），消费方须接受其 API 形态（async 返回 boolean）；验证面受限——降级路径无法在 127.0.0.1 直接复现，须以源码扫描测试 + 公网端到端判据双通道覆盖。dsh web 侧剪贴板缺口另有外挂 polyfill 通道（见知识页 dsh-web-clipboard-fallback），两侧前端机制独立、不合并。
