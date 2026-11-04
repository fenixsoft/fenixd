# ADR-324：全站标题栏唯一控件 + 声明-注册-插槽机制

date: 2026-11-04
status: accepted

## Context

dashboard 前端 8 个常规页各自以 `PageContainer header={{ title, subTitle, extra }}` 在内容区自画标题行，页级过滤控件散落两处形态（页头 extra / 页签 tabBarExtraContent）；embed=1 与移动端两类壳位差异使「每页两套标题形态」的重复面进一步放大。顶栏插槽（ProLayout header 插槽）位于布局配置层，页内组件无法直接向其塞节点——跨层承载需要一个桥接机制。备选方案「每页自渲染两种形态」被用户点名禁止，「全局路由表配标题」装不下页内状态（过滤项/富标题）。

## Decision

全站内容标题栏收敛为唯一控件（`PageTitleBar`，四槽位 title/subtitle/back/filters），页面只声明数据、MUST NOT 逐页自画同类型标题 div 或自选过滤落点。壳位判定（embed=1 或视口 <768 → 内容区首行行壳位；否则顶栏壳位）收敛在控件内部，页面侧零环境分支。顶栏承载走声明-注册-插槽：控件挂载即把 meta 登记进模块级注册表，布局层（app.tsx headerContentRender / actionsRender 插槽）消费渲染；注册与注销由同一 effect 的 cleanup 承担，顶栏无注册渲染空。壳位单源互斥是硬约束：同一 meta 任一时刻只渲染于一处，跨 768px 阈值切换必须清理退出侧，不得双标题并存或残留。配套约束：PageContainer 本体保留承载留白 token 单源（禁止整体换裸 div），常规页必须 `title={false}` 显式抑制其路由名兜底自动页头。

## Consequences

后续任何新增/改造 dashboard 页面的 SPEC 实现空间被约束：标题与过滤项只能经本控件声明，另立第二标题控件、恢复逐页页头或新增散落过滤落点均属禁止复辟面，须显式 supersede 本裁定。代价：引入一层注册表间接（页面状态与布局层经共享 store 桥接，多一跳数据流）；resize 跨阈值清理与路由切换注销时序成为必须守住的正确性面（闪烁/残留回归风险）；豁免面（layout:false 脱壳页、/projects 兜底占位页）游离在机制之外，属显式白名单而非机制自动豁免。
