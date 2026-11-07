# dsh settings 架构契约与 settings-dock 插件返工三点（2026-11-07）

fenix-dsh-settings-dock 插件（dsh-plugins 仓 6bb4a2c）交付中的 dsh 0.2.0-rc.2
构建产物契约与真机返工教训，后续 dsh 插件开发可复用。

## dsh settings UI 架构（0.2.0-rc.2 实测）

- 设置弹窗壳在 `dsh-client-ui-settings-general`：body 直挂 portal →
  `div[role=presentation]` 全屏 overlay（flex 居中、z=1000）> `[aria-hidden]`
  遮罩（点击关闭层）+ 面板（固定 800×800）。十个官方 section（models/plugins/
  agent-preset/account…）经 `settings.section` 插槽注册进壳，各包自持 CSS。
- 稳定钩子：面板带官方非哈希属性 `[data-shortcut-modal="settings"]`；
  侧栏列 `[class*="sidebarCol"]`；拖拽把手 `[data-side="sidebar"]`（收缩态
  **不渲染**）；右栏 `[data-rightbar-col]`；各 section 根唯一类片段
  `<hash>_section`（全 settings 族核实无 `_section*` 变体）。
- `useModalLayer`（primitives）只做文档级 Esc + Tab 焦点圈：**不设 inert、
  不拦指针**——页面化改造无官方阻碍；但官方模态语义（`aria-modal=true`）
  被 `closeTopModal` 快捷指令按 `modalSelector` 消费，停靠类插件**不可翻转
  aria-modal**，否则关闭指令失配。
- 侧栏宽度 JS 驱动可拖拽、无 CSS 变量；收缩态官方语义 = 残留 56px 窄轨
  （非列宽 0）；设置触发按钮点击是 `openSettings()` **幂等开**，无 toggle
  语义（官方模态下开态点不到它，从未暴露）。

## 真机返工三点（第一版全踩）

1. **pointer-events 继承淹没**：overlay 设 `pointer-events:none` 放行侧栏
   点击，该属性**继承**导致面板内容全部不可点——父层放行时子面板必须显式
   `pointer-events:auto` 取回。
2. **测量锚缺席≠几何为零**：以拖拽把手为侧栏锚时，收缩态把手卸载被误判为
   列宽 0，面板盖住 56px 窄轨；测量锚要选全形态在场的元素（sidebarCol 列），
   把手只配当兜底。
3. **停靠页遮蔽后台切换**：设置停靠内容区后，侧栏点击照常切面板但被停靠页
   盖住，观感「点了没反应」。页面化插件需配 capture 阶段侧栏区点击 → 合成
   Esc 收设置（`useModalLayer` 文档级监听吃合成 keydown）；触发按钮另需
   stopPropagation 拦截官方 open() 代管为 toggle。
