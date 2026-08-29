## Context

JSSDK 默认 pathname 路由,v2 需 hash 路由以兼容现有 `#/overview` 风格链接。官方 examples/app/index.jsx 提供完整移植示例(约 100 行):自定义 env 三方法(jumpTo/updateLocation/isCurrentUrl)+ hashchange 时 `amisScoped.updateProps({location})`。

## Goals / Non-Goals

- Goals: 5 个路由模式可用(#/overview、#/project/:name、#/spec/:project/:name、#/config[/:project]?tab=、#/activities[/:project]);app 组件壳渲染侧边导航;Playwright 冒烟通过
- Non-Goals: 页面 body 内容(后续 SPEC);SSE(下一 SPEC)

## Decisions

- **app 组件壳**(方案 A,用户已确认):导航/参数路由/页面按需渲染白拿;SSE 桥(Task 3)挂壳级 header
- **页面 JSON 构建期合并**:app.js fetch `pages/*.json`(带 `?t=Date.now()` 防缓存)按 url 前缀深合并进 app schema;单个页面 404 时 catch 跳过,使后续 SPEC 可并行加页面
- **占位 JS 文件**:index.html 一次引齐 5 个脚本避免后续改动;adapters/bridge/run-stream 先以空对象占位
- **深链**:config 页签用 `defaultKey: "${query.tab}"`(后续 config SPEC 落地);路由模式串与老版一致(behavior.md §8)

## Risks / Trade-offs

- 字符串形式的 onMount/schema 在 SDK 模式的执行语义需实测;若 app.json 内字符串函数不生效,退路是在 app.js 里全局注册 custom 渲染器(计划 Task 3 Step 3 已注明)
