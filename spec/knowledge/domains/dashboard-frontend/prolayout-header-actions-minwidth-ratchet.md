# ProLayout 顶栏动作区 min-width 棘轮锁

<!-- knowledge: capability=prolayout-header-actions-minwidth-ratchet rev=1
     sources=spec/knowledge/_inbox/done/prolayout-header-actions-minwidth-ratchet.md -->

ProLayout 顶栏动作区（right-content，统一标题栏 filters 槽的顶栏渲染位，槽位契约见 `unified-page-title-bar`）的宽度钳制规则：global.less 单源恒零化 pro-layout 内置 min-width 棘轮自锁，保证 SPA 切页后顶栏标题区不被残留锁宽挤压。

## 规则

- **棘轮自锁机制**：pro-layout GlobalHeader（ActionsContent）给顶栏动作区 `.ant-pro-global-header-right-content` 写内联 `min-width`——ResizeObserver 实测动作区内容宽、160ms 防抖回写，意图是防动作区被标题挤压。缺陷在自锁：min-width 一旦锁宽，被观测的内层元素随之撑到同宽，宽度永不回缩、观测器永不触发，锁只升不降。
- **触发链与症状签名**：顶栏挂过宽组件（运维页 filters 槽「全部项目」Select，minWidth 200、实测锁 216px）的页面，SPA 切走后组件卸载但 min-width 锁残留整个会话期，窄视口顶栏标题区被锁挤占——390px 下 SPEC 列表富标题「fenixd 共 525 个 SPEC」被挤成 75px 宽、竖排一字一行。凡顶栏挂过宽组件的页面在窄视口都可能复现（非运维页特有），桌面宽视口不可见。「SPA 导航后异常、直连加载同页正常（162px 单行）」即本缺陷签名。
- **global.less 单源修正（常驻勿删）**：`#root .ant-pro-global-header-right-content { min-width: 0 !important; }`（!important 压 pro-layout 内联样式）+ `#root .ant-pro-global-header-header-actions-item { flex-shrink: 0; }`——收缩由标题区承担（HeaderSlot flex:1 + minWidth 0，标题长时先缩、不挤动作区）。删除任一行即棘轮回归。
- **顶栏挂宽组件零额外处理**：filters 槽挂载惯例不受修正影响——新页面往顶栏挂宽组件无需任何处理，390px 下标题与 200px Select 同排放得下（运维页 Select 实测完整渲染）。

## 关键行为

- **分态复现对照**：390px 视口下直连加载与 SPA 路径（经挂宽组件页中转）对照同一页面——正常态标题单行 162px，缺陷态 75px 竖排一字一行。
- **宽度占用测量**：缺陷态 right-content 持内联 `min-width: 216px` 且内部最深元素仅 4px——宽度全部来自锁、非真实内容宽；正常态无内联 min-width、宽度自适应。
- **排查定式**：先分态复现，再对顶栏 children 逐元素量宽找膨胀元素，最后读 computed style 定位内联写入方（本例为 pro-layout ActionsContent.js）。

## 溯源

- 2026-11-07 prolayout-header-actions-minwidth-ratchet（spec/knowledge/_inbox/done/prolayout-header-actions-minwidth-ratchet.md） — 新建本页：顶栏动作区 min-width 棘轮自锁机制（ResizeObserver 实测回写、锁宽后观测元素同步撑宽只升不降）与触发链（filters 槽宽组件 SPA 残留挤压标题）、global.less 单源恒零化两行勿删、顶栏挂宽组件零额外处理、分态复现与逐元素量宽排查定式
