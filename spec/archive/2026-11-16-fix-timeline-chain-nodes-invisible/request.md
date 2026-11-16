另一个问题是spec的运行时间轴中，并没有看到arbiter的处理节点。
（排查结论）后端时间轴已下发链事件节点（chain-handoff/chain-escalated/chain-closed 等），前端 SpecTimeline 兜底守卫把 kind!=='run' 降级为裸灰点无卡片体——处置链节点实际不可见，需补链节点渲染。
