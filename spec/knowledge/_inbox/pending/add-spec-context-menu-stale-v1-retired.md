# add-spec-context-menu 知识页陈旧：v1 右键菜单已随 v1 dashboard 整体退役

- 知识页 `spec/knowledge/domains/dashboard-frontend/add-spec-context-menu.md`（rev 2，2026-11-10 仍更新）把「SPEC 行右键自绘菜单（呼叫 Admin/调整优先级/删除）」描述为现行规则，但现行前端源码（v3）中 `contextmenu` 处理为零（static/src 与 static/tests 全量 grep 无命中）。
- 退役点：v1 dashboard 的 `SpecContextMenu` 组件随 `ea88dd5a7`（chore: 移除已废弃的 v1/v2 dashboard，根路由 302 重定向到 v3）整体删除；现行行操作已收敛为操作列 ⋮ Dropdown（`specMenuItems`/`onSpecMenu`，`list.tsx:2245` 起）与移动卡 ⋮ 菜单。该页此后两次维护（rev 2 随 add-spec-info-icon-tooltip 收口措辞）都未发现描述对象已不存在——回填蒸馏时按代码锚点核验「页描述交互在现行源码是否仍有接线」可防此类漂移。
- 影响：该页现行规则段整体失效（交互契约、边缘翻转、关闭语义描述的是已删代码）；其「交互质量基线」（外点/Esc/滚动关闭、边缘翻转、portal 命中面隔离）作为设计先例仍有参考价值。2026-11-16 `add-spec-name-copy-menu` 立项时以 antd Dropdown `trigger={['contextMenu']}` 重建名称列右键交互（单项「复制 SPEC 名称」），不复活 v1 自绘实现——菜单交互契约由 antd 组件原生提供。
- 建议处置：退役该页或改写为「v1 右键菜单退役注记 + 交互基线先例」；归档蒸馏随 `add-spec-name-copy-menu` 收口时一并处理 `dashboard-spec-table` 域页与 index 条目。
