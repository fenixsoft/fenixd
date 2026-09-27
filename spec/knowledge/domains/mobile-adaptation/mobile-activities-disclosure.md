<!-- knowledge: capability=mobile-activities-disclosure rev=1 sources=spec/archive/2026-09-13-fix-mobile-touch-disclosure -->

# 运维记录渐进披露

运维记录页处置卡在移动端的长内容渐进披露契约：长摘要折叠展开、操作安全信息永不折叠、SSE 重渲不串卡。

## 规则

- isMobile 页面级持有：运维记录页在页面级调用 `useIsMobile()` 并下传至卡片组件，不采用每卡自调 hook。
- 长摘要折叠条件：仅当视口 <768px 且处置记录 summary 长度 >300 字符时，summary 正文默认折叠（maxHeight + overflow:hidden + 渐隐 mask 提示，折叠态正文可视高度约 110px 以内），卡下方呈现「展开全文/收起」切换按钮；展开与收起可往返，按钮文案随状态切换。
- 短摘要与桌面不折叠：summary ≤300 字符的卡片与 ≥768px 视口恒为全文展开，无切换按钮。
- 操作安全信息永不折叠：处置卡的失败原因、处置（actions_taken）、建议（recommended_action）区块在任何视口、任何 summary 长度下全文直接可见——其为操作安全信息，折叠可能误导处置决策。
- Timeline 稳定 key：运维记录 Timeline 的 items 为每个条目提供稳定 `key`（如记录 id），SSE 重拉重渲时 React 不按位置复用节点，各卡展开状态不串位。

## 溯源

- 2026-09-13 fix-mobile-touch-disclosure — 建立移动端长摘要折叠/展开契约（>300 字符阈值、安全信息豁免折叠）并为 Timeline items 补稳定 key
