# 嵌入挂载（dashboard-embed-mount）增量

## ADDED Requirements

### Requirement: 主题初始注入参数

挂载 search SHALL 支持可选参数 `theme`（值域 `dark|light` 白名单），由 `src/utils/embedMount.ts` 与既有 `apiBase`/`embed` 参数同模式解析（惰性缓存、独立解析、可组合、互不干扰；测试注血 `_setEmbedSearchParamsForTest` 同步覆盖）。参数含义为宿主解析后的初始主题档：`theme=dark` 时嵌入首帧呈深色，`theme=light` 时呈浅色；参数缺省或值非法时 SHALL 回退独立主题逻辑（localStorage + prefers-color-scheme），既有行为不变。参数承载在 location.search（hash 之前），与既有参数同等不随 hash 导航变化。

#### Scenario: 合法值注入

- **WHEN** 挂载 URL 携带 `embed=1&apiBase=/fenix-dashboard&theme=dark`
- **THEN** `embedMountConfig().theme` 解析为 `dark`，嵌入首帧呈深色；`apiBase`/`embed` 解析结果与无 `theme` 参数时逐字节一致

#### Scenario: 缺省与非法值回退

- **WHEN** 挂载 URL 无 `theme` 参数，或 `theme=purple`
- **THEN** 主题解析按独立逻辑执行（`theme` 视为未注入），`apiBase`/`embed` 行为与现状完全一致

#### Scenario: 参数组合互不干扰

- **WHEN** 挂载 URL 携带全部三参数且 hash 路由切换（如 `#/projects` → `#/settings`）
- **THEN** `theme` 与 `apiBase`/`embed` 解析值保持稳定不变（search 不随 hash 导航变化），页面路由正常
