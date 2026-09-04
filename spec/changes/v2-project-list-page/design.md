## Context

behavior.md §2 是列定义/过滤规则/fix 树规则的唯一权威;§5 是 Why 懒加载端点与 spec-error-clear。componentId:spec-crud 响应 sse:state。行数据来源 adapters.adaptSpecs(v2-data-adapters SPEC)。

## Goals / Non-Goals

- Goals: 列表渲染+排序+过滤+树形分组;行内三操作可用;error 子行信息与 Why 懒加载可访问;删除后列表刷新
- Non-Goals: 呼叫 Admin 的完整弹窗(Task 9,本 SPEC 先 toast 占位);详情页(Task 7)

## Decisions

- **树行渲染**:adaptSpecs 已输出 children 树,crud/table 原生渲染;展开方式以 6.13 经典 table 实测为准(footable 或 expandConfig,计划 Task 6 Step 3 注明)
- **行内 dropdown 替代右键菜单**(形态可变,用户已确认):三按钮分别为呼叫 Admin(占位 toast)、调优先级(Dialog+form POST /api/spec-priority)、删除(confirm+POST /api/spec-delete)
- **优先级请求体字段**:以 behavior.md §1 为准;若为枚举用 input-select
- **error/Why 用详情 Dialog**:懒加载 /api/specs/<spec> 的 error 与 why 字段(端点/字段 behavior.md §5),Dialog 内「清除错误」POST /api/spec-error-clear 后 reload spec-crud;去掉 200ms hover 特技

## Risks / Trade-offs

- 经典 crud 树行展开配置在 6.13 的确切属性名需实测;以测试通过为准
- 409(删除运行中 SPEC)由 AMIS ajax 默认错误 toast 呈现,时序窗口遵守全局约束(成功 5s/错误 6s)
