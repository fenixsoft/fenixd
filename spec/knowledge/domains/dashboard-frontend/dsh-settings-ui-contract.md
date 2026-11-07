# dsh 设置 UI 架构契约与停靠插件

<!-- knowledge: capability=dsh-settings-ui-contract rev=1
     sources=spec/knowledge/_inbox/done/dsh-settings-dock-plugin-1107.md -->

dsh web 官方设置弹窗的壳层结构、稳定钩子与模态语义契约（dsh 0.2.0-rc.2 构建产物实测），以及把该弹窗页面化停靠（`fenix-dsh-settings-dock` 插件）必须遵守的宿主交互规则。契约面对一般 dsh 插件开发同样可复用。

## 规则

- **设置弹窗壳结构**：壳在 `dsh-client-ui-settings-general`——body 直挂 portal → `div[role=presentation]` 全屏 overlay（flex 居中、z=1000）→ `[aria-hidden]` 遮罩（点击关闭层）+ 面板（固定 800×800）。官方 section（models/plugins/agent-preset/account 等十个）经 `settings.section` 插槽注册进壳，各包自持 CSS。
- **稳定钩子面**：面板带官方非哈希属性 `[data-shortcut-modal="settings"]`；侧栏列 `[class*="sidebarCol"]`；拖拽把手 `[data-side="sidebar"]`（收缩态不渲染）；右栏 `[data-rightbar-col]`；各 section 根唯一类片段 `<hash>_section`（全 settings 族核实无 `_section*` 变体）。哈希段随构建变、语义段稳定，选择器一律属性包含匹配。
- **useModalLayer 语义边界**：primitives 的 `useModalLayer` 只做文档级 Esc + Tab 焦点圈，不设 inert、不拦指针——把模态页面化停靠无官方阻碍；但面板官方 `aria-modal=true` 被 `closeTopModal` 快捷指令按 `modalSelector` 消费，停靠类插件不可翻转 aria-modal，否则关闭指令失配。
- **侧栏宽度无 CSS 变量**：侧栏宽度由 JS 驱动可拖拽，没有可读的 CSS 变量——几何测量只能取元素 rect。
- **收缩态 = 56px 窄轨**：侧栏收缩态官方语义是残留 56px 窄轨，不是列宽 0。
- **设置触发按钮是幂等开**：官方设置触发按钮点击即 `openSettings()` 幂等开，无 toggle 语义（官方模态形态下开态点不到该按钮，toggle 缺口从未暴露）——停靠插件要 toggle 必须自行拦截代管。
- **overlay 放行后子面板取回指针**：overlay 层设 `pointer-events:none` 放行侧栏点击时，该属性被面板内容继承导致全部不可点——父层放行时停靠面板必须显式 `pointer-events:auto` 取回。
- **测量锚选全形态在场元素**：几何测量锚 MUST 选全形态在场的元素（`sidebarCol` 列）；拖拽把手在收缩态卸载，以其为锚会把把手缺席误判为列宽 0、面板盖住 56px 窄轨——把手只配当兜底锚。
- **停靠页必须配收页通道**：设置停靠为内容区后，官方侧栏点击照常切面板但被停靠页盖住（观感「点了没反应」）——页面化插件需在 capture 阶段监听侧栏区点击并合成 Esc 收设置（`useModalLayer` 的文档级监听会消费合成 keydown）；设置触发按钮需 `stopPropagation` 拦截官方 `openSettings()`、代管为 toggle。

## 关键行为

插件源码在 dsh-plugins 仓 `fenix-dsh-settings-dock`。契约口径来自 dsh 0.2.0-rc.2 构建产物真机实测，哈希类名与壳层结构随构建可能漂移——dsh 版本升级时钩子面需复核。部署与验证链同 dsh 插件族：改源码 → `pnpm build`（lib/ 产物经 symlink 即时映射）→ `systemctl restart dsh-web` → `/var/log/dsh-web.log` 尾部取 token URL 重登，playwright 命名会话（`-s` 隔离）实拍验证。

## 溯源

- 2026-11-07 dsh-settings-dock-plugin-1107（spec/knowledge/_inbox/done/dsh-settings-dock-plugin-1107.md） — 新增本能力：设置弹窗壳结构与 settings.section 插槽、稳定钩子面、useModalLayer 语义边界（不拦指针、aria-modal 不可翻转）、侧栏宽度 JS 驱动与 56px 窄轨与触发按钮幂等开、停靠页面化三规（overlay 放行后 pointer-events 取回、全形态在场测量锚、capture 合成 Esc 收页与触发按钮 toggle 代管）
