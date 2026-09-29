<!-- knowledge: capability=mobile-breakpoint-unification rev=1 sources=spec/archive/2026-09-13-fix-mobile-breakpoint-hook-tables -->

# 移动断点统一

dashboard 前端移动端 CSS 与 JS 两轨断点的统一约定：全部移动端样式收敛到同一视口边界 <768px，与 `useIsMobile` 判定一致。

## 规则

- 移动端 CSS 作用域：`core/dashboard/static/src/global.less` 中全部移动端规则统一使用 `#root :is(.screen-xs, .screen-sm)` 作用域前缀，有效边界为 <768px，与 `hooks/useIsMobile.ts` 的 `(max-width: 767.98px)` 判定对齐（screen-xs = <576px，screen-sm = 576–767px）。文件内保留说明该约定的注释。
- screen-sm 区间（576–767px）内移动端排版照常生效：PageContainer 内容区 `.ant-pro-page-container-children-container` 的 padding-inline 为 12px（桌面为 24px/40px）；设置页表单 label 以 block 排版正常换行。
- PC 端零影响：视口 ≥768px（screen-md/lg/xl/xxl）下 `:is(.screen-xs, .screen-sm)` 规则全部不命中，桌面渲染不受移动端规则影响。
- 全站 Modal 移动端宽度上限：global.less 的移动端作用域规则使任何 `.ant-modal` 在 <768px 视口下宽度不超过 `calc(100vw - 32px)`；Modal 宽度写死（如 520px）时按此上限收敛，不横向溢出视口。≥768px 视口 Modal 宽度保持桌面设定值。

## 溯源

- [2026-09-13 fix-mobile-breakpoint-hook-tables](spec/archive/2026-09-13-fix-mobile-breakpoint-hook-tables/) — 确立 `:is(.screen-xs, .screen-sm)` 统一作用域约定（覆盖既有全部移动端规则），并追加全站 Modal 移动端宽度上限
