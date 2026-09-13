## ADDED Requirements

### Requirement: 运维记录长摘要移动端渐进披露
运维记录页 SHALL 在页面级持有 `useIsMobile()` 并下传至卡片组件（不采用每卡自调 hook）。仅当视口 <768px 且处置记录 summary 长度 >300 字符时，summary 正文 SHALL 默认折叠（maxHeight + overflow:hidden + 渐隐 mask 提示），并呈现「展开全文/收起」切换按钮；展开/收起 SHALL 可往返。短摘要（≤300 字符）与 ≥768px 视口 SHALL 恒为全文展开且无切换按钮。

#### Scenario: 长摘要默认折叠
- **WHEN** 390px 视口打开运维记录页，存在 summary 超过 300 字符的处置卡
- **THEN** 该卡 summary 默认收起（正文可视高度 ≤ ~110px 并带渐隐提示），卡下方出现「展开全文」按钮；整页高度较全部展开显著下降

#### Scenario: 展开收起往返
- **WHEN** 390px 视口点击长摘要卡的「展开全文」再点击「收起」
- **THEN** 正文完整展开、再次收起，按钮文案随状态切换

#### Scenario: 短摘要与 PC 端不折叠
- **WHEN** 390px 视口查看 summary ≤300 字符的卡片，或 ≥768px 视口查看任意卡片
- **THEN** summary 全文展开，无「展开全文」按钮

### Requirement: 操作安全信息不折叠
处置卡的失败原因、处置（actions_taken）、建议（recommended_action）区块 SHALL 永不折叠（任何视口、任何 summary 长度）——其为操作安全信息，折叠可能误导处置决策。

#### Scenario: 安全信息始终可见
- **WHEN** 390px 视口查看含失败原因与建议的长摘要卡（默认折叠态）
- **THEN** 失败原因、处置、建议区块全文直接可见，仅 summary 正文被折叠

### Requirement: Timeline 节点稳定 key
运维记录 Timeline 的 items SHALL 为每个条目提供稳定 `key`（如记录 id），防止 SSE 重拉重渲时 React 按位置复用导致展开状态串卡。

#### Scenario: SSE 刷新后展开态不串卡
- **WHEN** 390px 视口展开某长摘要卡后，该页收到 SSE 推送触发列表重渲
- **THEN** 该卡保持展开态，其他卡片展开态不发生错位串卡
