## REMOVED Requirements

### Requirement: 移动端隐藏顶栏全局面包屑
**Reason**: 面包屑已随 unified-page-title-bar 全局移除（全部视口宽度），「<768 隐藏、≥768 显示」的宽度分档语义失去对象。
**Migration**: 顶栏无面包屑成为全宽度常量事实；位置指示职责由统一标题栏控件的页面标题承担（见 unified-page-title-bar「顶栏面包屑退役」）。

## MODIFIED Requirements

### Requirement: 详情页标题 Tag 行窄屏换行
spec 详情页富标题组合（SPEC 名 + 模式 Tag + 状态 Tag + 切换下拉）的载体由 PageContainer `headerCfg` title 的 Space 容器迁移到统一标题栏控件（unified-page-title-bar）的行壳位（<768px 视口下标题栏渲染在内容区首行）。该组合 SHALL 允许换行（`wrap`），390px 视口下不横向溢出。桌面端内容不溢出时 flex-wrap 无视觉差异。

#### Scenario: 移动端 Tag 行不溢出
- **WHEN** 390px 视口打开长名称 SPEC 的详情页
- **THEN** 内容区首行标题栏内 SPEC 名与 Tag 们自然换行显示，页面 `scrollWidth` 不超过 390，无横向溢出；切换下拉保持在 SPEC 名旁
