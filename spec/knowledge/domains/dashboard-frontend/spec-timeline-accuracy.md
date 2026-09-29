<!-- knowledge: capability=spec-timeline-accuracy rev=1 sources=spec/archive/2026-09-14-fix-timeline-substring-leak -->

# 时间轴准确性

SPEC 详情时间轴的名称隔离与方向保真：日志行按完整 spec 名归属，回退徽标按方向渲染。

## 现行规则

- `get_spec_timeline` 解析 daemon 日志时按完整 spec 名精确匹配行归属：`Updated SPEC` 行以带引号的全名形态（`'<spec_name>'`，与 state_machine 日志文案一致）判定；`Transition:` 行维持「名字后紧跟空白」的正则锚定。
- 前缀名 spec（如 `add-foo`）不吸收更长名字姊妹 spec（如 `add-foo-ui`）的任何状态节点；姊妹 spec 自身时间轴不受影响；from 推演同样不被姊妹 spec 更新污染。
- 状态节点携带 `backward` 布尔（按生命周期序判定 to 是否早于 from），`Transition:` 解析与打回重建两条路径统一输出该字段。
- 回退重建文案：回退节点无同行 error 时可用规则兜底文案；前向节点不得得到「状态回退」类兜底文案——无同行 error 时 reason 为空（可被折叠链合并），有同行 error 时 reason 为该 error 且不视为回退。
- 就近 error 覆写（≤10 分钟窗口）仅作用于回退节点或带同行 error 的节点，不覆写前向直写节点。
- 前端「↩ 状态回退」徽标依据 `backward` 字段渲染（backward=true 才显示）；`backward` 缺失的存量数据回退既有 `!!reason` 判定保持兼容；reason 文案展示不随方向变化。

## 溯源

- [2026-09-14 fix-timeline-substring-leak](spec/archive/2026-09-14-fix-timeline-substring-leak/) — 根治前缀名子串吸收姊妹 spec 状态节点：`Updated SPEC` 全名精确匹配、`backward` 方向字段双路径统一输出与前端回退徽标按方向渲染
