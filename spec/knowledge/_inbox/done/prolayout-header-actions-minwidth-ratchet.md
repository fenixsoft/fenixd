# pro-layout 顶栏动作区 min-width 棘轮锁（运维页切页标题竖排挤压）

## 背景

2026-11-07 用户报告：进入运维页（/activities）后再点其他页（如 SPEC 列表
/projects/fenixd），顶栏标题显示不正常——移动端 390px 下 SPEC 列表富标题
「fenixd 共 525 个 SPEC」被挤成 75px 宽、竖排一字一行；直连加载同一页面
则完全正常（162px）。SPA 导航相关、直连不相关，是状态残留类缺陷。

## 结论（当前生效规则）

1. **机制**：pro-layout `ActionsContent.js`（GlobalHeader）给
   `.ant-pro-global-header-right-content` 写内联 `min-width: rightSize`，
   rightSize 由 ResizeObserver 实测**内部动作内容宽**经 160ms 防抖回写，
   意图是防动作区被标题挤压。缺陷：min-width 锁宽后内部被观测元素随之撑到
   同宽，宽度永不回缩、观测器永不触发——**棘轮只升不降**（自锁）。
2. **触发链**：运维页处置链页签经统一标题栏 filters 槽在顶栏渲染「全部项目」
   Select（minWidth 200，实测锁 216px）→ SPA 切页后 Select 卸载但 216px 锁
   残留会话期 → 390px 顶栏标题区被挤。桌面视口宽、不可见；凡顶栏挂过宽组件
   的页面在窄视口都会复现，非运维页特有。
3. **当前生效规则（global.less 单源）**：
   `#root .ant-pro-global-header-right-content { min-width: 0 !important; }`
   （!important 压 pro-layout 内联样式）+
   `.ant-pro-global-header-header-actions-item { flex-shrink: 0; }`——收缩
   由标题区承担（HeaderSlot flex:1 + minWidth:0，标题先缩不挤动作）。新页面
   往顶栏挂宽组件时无需额外处理，但勿删此修正（删则棘轮回归）。
4. **顶栏 filters 槽挂载惯例不受影响**：运维页 Select 实测仍 200px 完整
   渲染；390px 下标题（2 字）+ Select 同排放得下。

## 证据

- 复现/对照：直连加载 `#/projects/fenixd`（390px）标题 162px 单行正常；
  SPA 路径（运维页→汉堡→fenixd）同页标题 75px、竖排一字一行。
- 宽度占用测量：SPA 后 `right-content` w216 / 内联 `min-width: 216px`，
  内部最深元素仅 4px（216px 全部来自锁）；直连同元素 w4、无内联 min-width。
- pro-layout 源码：`ActionsContent.js` `style: { minWidth: rightSize }` +
  ResizeObserver onResize → 160ms 防抖 setRightSize；观测元素为 right-content
  内层 div（被 min-width 撑到同宽）。
- 修复后：同 SPA 路径标题 162px、rc minWidth=4px 自适应；运维页 Select 200px
  完整；测试 415/415。提交 `534d401a8`（global.less 单源）。
- 排查方法论备忘：这类「SPA 导航后异常、直连正常」先分态复现，再对顶栏
  children 逐元素量宽找膨胀元素（本例 right-content 216 vs 4），最后读
  computed style 定位内联写入方。
