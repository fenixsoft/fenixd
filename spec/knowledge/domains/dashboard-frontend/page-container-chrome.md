<!-- knowledge: capability=page-container-chrome rev=4
     sources=spec/knowledge/_inbox/done/memory-distill-user-rulings.md,spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md,spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md,spec/knowledge/_inbox/done/dashboard-smoke-prismlight-routes-1110.md -->

# 内容区留白与边框治理

页面容器留白与去边框（扁平化）的单源口径、零值传导陷阱与验证纪律。

## 规则

- 留白单源：页面容器水平留白由 ProLayout token `paddingInlinePageContainerContent` 单源承载（`theme.ts` 的 `dshLayoutToken` 设定），各页不得自带容器 padding 形成第二留白源。
- 页面内容区间距：内容区左右留白 15px（`dshLayoutToken` 单源承载）；页顶另加 16px 呼吸带，以页级标记类 `:has()` 作用于 `ant-layout-content`（现存标记类 `overview-page` / `spec-detail-page` 两页，标记类落页根包装 div）；embed 行壳位档豁免归零（下游 24px）。呼吸带由 pageChrome 守卫钉住（标记类接线 + 值与豁免档断言）。
- 零值传导靠尾部 spread：token 值 0 会被 `getLayoutDesignToken` 的 `||40` 类缺省兜底吞掉，0 值必须靠对象尾部 spread 展开覆盖传入才能生效，不能依赖前置赋值。
- 去边框页级作用域：去边框/扁平化治理按页级作用域生效，Modal 与脱壳页（独立挂载的无壳页面）豁免，不做全局一刀切。
- 前端验证必须 reload：前端改动 rebuild 后必须整页 reload 再验证——hash 路由 goto 只变更 hash 不重载文档，不 reload 会拿旧 bundle 验证新改动。
- hash 路由入口必须带 `/#/`：dashboard 前端为 hash 路由（如 `http://127.0.0.1:8787/#/projects/fenixd?tab=home`），浏览器冒烟从空白页 goto 必须使用 `/#/<路径>` 形态；直接访问路径形态（`/projects/<name>`）会让 `dist/index.html` 的 `./umi.*.js` 相对资源引用解析成 `/projects/umi.*.js` → css/js/preload_helper 全 404 白屏（console 三条资源错误）。
- 定高贴底豁免：children 容器 `padding-block-end: 0`（pro-layout token `paddingBlockPageContainerContent` 缺省 8px 归零）全局生效——该底部内边距对定高贴底页是溢出源，卡片按视口裁齐后会把文档流顶出第二根滚动条。现存定高贴底页仅项目详情页框（`pageChrome.ts`）与指挥中心（`SCREEN_CHROME_OFFSET`）两类；帮助/设置页为文档级滚动、不贴底，同享归零口径（不按页回填）。顶部内边距本为 0 不动，左右留白归 `dshLayoutToken` 单源管辖。

## 溯源

- 2026-11-04 memory-distill-user-rulings（spec/knowledge/_inbox/done/memory-distill-user-rulings.md） — 新建本页：折叠留白单源 token 口径（含 `||40` 吞 0 与尾部 spread）、去边框页级作用域豁免、rebuild 后 reload 验证纪律
- 2026-11-05 settings-help-document-scroll-unify（spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md） — 新增 children 容器 padding-block-end 归零规则：定高贴底页现存面为项目详情页框与指挥中心，帮助/设置页文档级滚动不贴底、同享归零不按页回填
- 2026-11-06 overview-ledger-bento-align-1106（spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md） — 新增页面内容区间距条款：左右 15px（dshLayoutToken 单源）+ 顶呼吸带 16px（页级标记类 :has() 作用 ant-layout-content，现存 overview-page / spec-detail-page 两页，embed 行壳位档豁免归零）
- 2026-11-10 dashboard-smoke-prismlight-routes-1110（spec/knowledge/_inbox/done/dashboard-smoke-prismlight-routes-1110.md） — 新增 hash 路由入口纪律：入口必须带 `/#/`，路径形态令 dist `./umi.*` 相对资源引用解析 404 全白屏，与 reload 纪律同族构成前端冒烟加载纪律
