<!-- knowledge: capability=page-container-chrome rev=1
     sources=spec/knowledge/_inbox/done/memory-distill-user-rulings.md -->

# 内容区留白与边框治理

页面容器留白与去边框（扁平化）的单源口径、零值传导陷阱与验证纪律。

## 规则

- 留白单源：页面容器水平留白由 ProLayout token `paddingInlinePageContainerContent` 单源承载（`theme.ts` 的 `dshLayoutToken` 设定），各页不得自带容器 padding 形成第二留白源。
- 零值传导靠尾部 spread：token 值 0 会被 `getLayoutDesignToken` 的 `||40` 类缺省兜底吞掉，0 值必须靠对象尾部 spread 展开覆盖传入才能生效，不能依赖前置赋值。
- 去边框页级作用域：去边框/扁平化治理按页级作用域生效，Modal 与脱壳页（独立挂载的无壳页面）豁免，不做全局一刀切。
- 前端验证必须 reload：前端改动 rebuild 后必须整页 reload 再验证——hash 路由 goto 只变更 hash 不重载文档，不 reload 会拿旧 bundle 验证新改动。

## 溯源

- 2026-11-04 memory-distill-user-rulings（spec/knowledge/_inbox/done/memory-distill-user-rulings.md） — 新建本页：折叠留白单源 token 口径（含 `||40` 吞 0 与尾部 spread）、去边框页级作用域豁免、rebuild 后 reload 验证纪律
