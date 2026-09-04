## Context

dashboard 前端将从单文件 app.js 重构为 AMIS 6.13.0 JSON DSL(设计:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-design.md)。AMIS 以 SDK 形态(sdk.js + css)通过 script 标签引入,无构建链。npm tarball 已验证可下载(/tmp/amis-6.13.0.tgz,或重新 `npm pack amis@6.13.0`)。

## Goals / Non-Goals

- Goals: sdk 产物落盘 static/v2/;现有 ThreadingHTTPServer 零改动即可 serve
- Non-Goals: 不引入 npm/node 构建链到主项目;不裁剪 sdk 体积

## Decisions

- **vendor 而非 CDN**(用户已确认):内网工具,离线可用优先
- **仅取 5 个文件**:sdk.js、sdk.css、dark.css(v2 首版仅深色主题)、iconfont.css、helper.css;其余(ie11 css、xlsx、codemirror 等)不要
- **tarball 提取而非 npm install**:不污染项目 node_modules;`tar xzf /tmp/amis-6.13.0.tgz -C /tmp/amis-pkg package/sdk/{sdk.js,sdk.css,dark.css,iconfont.css,helper.css}` 后拷贝

## Risks / Trade-offs

- sdk.js 数 MB 入仓 → 接受(设计 §8);一次性 vendor
- 版本锁定 6.13.0 → 后续升级需重跑本流程,行为以 behavior.md 为回归基准
