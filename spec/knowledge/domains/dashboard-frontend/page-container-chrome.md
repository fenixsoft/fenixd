<!-- knowledge: capability=page-container-chrome rev=2
     sources=spec/knowledge/_inbox/done/memory-distill-user-rulings.md,spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md -->

# 内容区留白与边框治理

页面容器留白与去边框（扁平化）的单源口径、零值传导陷阱与验证纪律。

## 规则

- 留白单源：页面容器水平留白由 ProLayout token `paddingInlinePageContainerContent` 单源承载（`theme.ts` 的 `dshLayoutToken` 设定），各页不得自带容器 padding 形成第二留白源。
- 零值传导靠尾部 spread：token 值 0 会被 `getLayoutDesignToken` 的 `||40` 类缺省兜底吞掉，0 值必须靠对象尾部 spread 展开覆盖传入才能生效，不能依赖前置赋值。
- 去边框页级作用域：去边框/扁平化治理按页级作用域生效，Modal 与脱壳页（独立挂载的无壳页面）豁免，不做全局一刀切。
- 前端验证必须 reload：前端改动 rebuild 后必须整页 reload 再验证——hash 路由 goto 只变更 hash 不重载文档，不 reload 会拿旧 bundle 验证新改动。
- 定高贴底豁免：children 容器 `padding-block-end: 0`（pro-layout token `paddingBlockPageContainerContent` 缺省 8px 归零）全局生效——该底部内边距对定高贴底页是溢出源，卡片按视口裁齐后会把文档流顶出第二根滚动条。现存定高贴底页仅项目详情页框（`pageChrome.ts`）与指挥中心（`SCREEN_CHROME_OFFSET`）两类；帮助/设置页为文档级滚动、不贴底，同享归零口径（不按页回填）。顶部内边距本为 0 不动，左右留白归 `dshLayoutToken` 单源管辖。

## 溯源

- 2026-11-04 memory-distill-user-rulings（spec/knowledge/_inbox/done/memory-distill-user-rulings.md） — 新建本页：折叠留白单源 token 口径（含 `||40` 吞 0 与尾部 spread）、去边框页级作用域豁免、rebuild 后 reload 验证纪律
- 2026-11-05 settings-help-document-scroll-unify（spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md） — 新增 children 容器 padding-block-end 归零规则：定高贴底页现存面为项目详情页框与指挥中心，帮助/设置页文档级滚动不贴底、同享归零不按页回填
