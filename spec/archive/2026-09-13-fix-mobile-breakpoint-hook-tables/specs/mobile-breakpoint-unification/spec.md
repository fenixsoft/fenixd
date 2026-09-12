## ADDED Requirements

### Requirement: 移动端 CSS 作用域统一覆盖 <768px
`core/dashboard/static/src/global.less` 中的移动端规则 SHALL 统一使用 `#root :is(.screen-xs, .screen-sm)` 作用域前缀，使全部移动端 CSS 规则的有效边界与 `hooks/useIsMobile.ts` 的 `(max-width: 767.98px)` 对齐（screen-xs = <576px，screen-sm = 576–767px）。文件内 SHALL 保留说明该约定的注释，且旧注释中「screen-sm 命中不了」的错误表述 MUST 更正。

#### Scenario: 空窗带内留白收紧生效
- **WHEN** 视口宽度为 600px（原 576–768px 空窗带内）打开任意 PageContainer 页面
- **THEN** `.ant-pro-page-container-children-container` 的 padding-inline 为 12px（而非桌面 24px/40px）

#### Scenario: 空窗带内设置页 label 换行规则生效
- **WHEN** 视口宽度为 600px 打开设置页
- **THEN** 表单 label 以 block 排版正常换行（screen-sm 下 `.settings-page .ant-form-item-label label { display: block }` 命中）

#### Scenario: PC 端样式零影响
- **WHEN** 视口宽度 ≥768px（screen-md/lg/xl/xxl）
- **THEN** `:is(.screen-xs, .screen-sm)` 规则全部不命中，桌面端渲染与改动前逐像素一致

### Requirement: 移动端全站 Modal 宽度上限
global.less SHALL 追加移动端作用域规则，使任何 `.ant-modal` 在 <768px 视口下宽度不超过 `calc(100vw - 32px)`，防止 Modal 宽度写死（如 520px）时溢出视口。

#### Scenario: 固定宽度 Modal 不溢出视口
- **WHEN** 390px 视口下打开 HookManager 的新增/编辑 Hook Modal（桌面 width=520）
- **THEN** Modal 实际宽度 ≤ 358px（100vw - 32px），无横向溢出

#### Scenario: PC 端 Modal 宽度不受限
- **WHEN** 视口宽度 ≥768px 打开同一 Modal
- **THEN** Modal 宽度仍为桌面设定值（520px），行为与改动前一致
