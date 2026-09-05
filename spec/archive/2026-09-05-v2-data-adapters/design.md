## Context

behavior.md §1 的 API 字段表是字段名的唯一权威(有历史坑:verdict.summary 计数可能是字符串 "0";GET /api/config 无 llm 键时 llm 为空对象且没有 providers 数组——responseAdaptor 必须兜底;数字字段有「空/NaN→已加载快照→领域默认」三级回退,behavior.md §6)。

## Goals / Non-Goals

- Goals: 10 个导出全部实现且 node 单测通过;字段名与 behavior.md §1 逐字一致
- Non-Goals: 不做任何 API 请求(纯函数);不处理 SSE 帧

## Decisions

- **UMD 尾部**:`module.exports`/`window.Adapters` 双出口,node:test 与浏览器共用一份代码
- **fix 树在 adaptSpecs 内构建**:fix-<父名> 归入父名行 children,子行标 isFixChild:true,父行聚合子任务进度(behavior.md §2 规则逐字)
- **排序**:adaptSpecs 按 SPEC_LIFECYCLE 生命周期序输出(behavior.md §2 枚举顺序逐字)
- **数字化**:所有计数字段 Number() 归一,NaN→0(verdict "0" 字符串坑)
- **fixture 抓真实响应**:curl 现有 /api/ 端点存 api-samples.json,保证测试贴真实数据

## Risks / Trade-offs

- behavior.md §2 的 fix 树聚合规则若与 fixture 实况不符,以 fixture 实况为准修正并在 tasks 注明
