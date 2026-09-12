## Deliverables

```yaml
- path: core/dashboard/static/src/global.less
  kind: modify
- path: core/dashboard/static/src/components/HookManager.tsx
  kind: modify
```

## 1. 断点统一与全站防御

- [x] 1.1 global.less：将 L120–190 全部 15 条移动端规则的选择器由 `#root .screen-xs X` 机械替换为 `#root :is(.screen-xs, .screen-sm) X`（每条规则尾部不变），并重写 L133–135 注释为「移动端作用域 = screen-xs ∪ screen-sm = <768，与 hooks/useIsMobile.ts 的 767.98 对齐；ProLayout 根节点 390px 挂 screen-xs、600px 挂 screen-sm（2026-09-07 实测）」
- [x] 1.2 global.less 追加全站 Modal 移动端上限规则：`#root :is(.screen-xs, .screen-sm) .ant-modal { max-width: calc(100vw - 32px); }`

## 2. HookManager 横滚兜底

- [x] 2.1 HookManager.tsx 三张 Table（生效合并表 / Hook CRUD 表 / 最近执行审计表）各加 `scroll={{ x: 'max-content' }}`

## 3. HookManager 移动端卡片化

- [x] 3.1 HookManager 组件自持 `useIsMobile()`（import 自 `@/hooks/useIsMobile`）
- [x] 3.2 生效合并表 isMobile 分支卡片化：来源 Tag（全局/本 SPEC）+ 事件 Tag 列表 wrap、动作名 + 状态 Tag、paramSummary 全文 break-all；外层结构复用 SpecCardList 范式（List.Item 内 div width:'100%' minWidth:0）
- [x] 3.3 Hook CRUD 表 isMobile 分支卡片化：事件 Tag wrap + Switch size=small（disabled={readOnly}，onChange 绑既有 handleToggle）、动作 label、参数全文、「编辑」（handleEdit）/「删除」（Popconfirm→handleDelete）操作行，readOnly 时隐藏并保留既有「SPEC 已推送」提示
- [x] 3.4 审计表 isMobile 分支卡片化：时间 + 结果 Tag、SPEC 名（break-all）· 动作 label · 耗时、摘要 pre-wrap 全文
- [x] 3.5 空态分支（暂无 Hook 订阅 / 暂无执行记录）在两形态下共用不重复

## 4. 构建与双视口验证

- [x] 4.1 `cd core/dashboard/static && npm run build` 构建通过
- [ ] 4.2 playwright 390×844：spec 详情 Hook 页签与设置页项目作用域 Hook 面板 `document.scrollingElement.scrollWidth === 390`，表格容器内可横滑（兜底形态下）；卡片形态下三卡字段完整、Switch 启停即保存、编辑弹窗回填、删除 Popconfirm 生效、终态只读无编辑入口
- [ ] 4.3 playwright 600×900：原空窗带内页面留白 12px、设置页 label 换行规则生效
- [ ] 4.4 playwright 1920×1080 对照基线：三表列数列宽无滚动条、Modal 宽度 520、六页无差异；宽 390↔768 拖拽分支切换无报错

## 验证修复（第 1 轮失败）

- [x] 先复核失败有效性：逐条核对 `spec/changes/fix-mobile-breakpoint-hook-tables/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [ ] 修复后重跑验证确认通过
