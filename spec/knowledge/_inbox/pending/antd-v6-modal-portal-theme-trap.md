# antd v6 嵌套 ConfigProvider 主题与 claude-msg 主题跟随（2026-11-25 深色档排查）

## 现象

深色宿主下把亮色算法 ConfigProvider 外提包住 antd Modal（RunRecordModal），壳（标题/关闭钮/容器底）仍按外层深档算法渲染（title 实测 rgb(249,250,251)）；同一 Provider 对普通子树立即生效。

## 结论

antd v6（6.6.2）Modal 的 portal 内容取不到嵌套 Provider 的主题作用域（壳 token 仍取根档），且 v6 语义键已把 `content` 改名为 `container`（`.ant-modal-content` 选择器不存在）。若某弹窗需要**固定亮锁**（如亮面家族），壳必须用 `styles` 语义键显式定值：`container/header/title/close` 四键（AdminRunModal 需把 styles 放在 `{...modalProps}` 之后并 `...modalProps.styles` 合并保住最大化 body 几何）。

## 最终口径（2026-11-25 二轮用户指令 supersede）

用户裁定 Agent 运行记录（内嵌展开/RunRecordModal/AdminRunModal）**跟随主题**而非亮锁：撤全部亮锁 ConfigProvider 与固定 chrome styles，改为——

- claude-msg shadcn 变量（HSL 三元组）按 `[data-fenix-theme='dark']` 在 global.less 双档覆盖（pane/portal 同组，bg #151517/card #232324/popover #2c2c2e/fg #f9fafb/muted-fg #adb2b8/primary #7aaaff）。
- tailwind typography 的 `.prose/.prose-gray` 在元素上**直写**浅档 statics，祖先变量继承不生效——深档须以 `[data-fenix-theme='dark'] … :is(.prose,.prose-gray)`（特异性 0,3,0）在 `.prose` 本体重定义 `--tw-prose-*`。
- 亮锁面（若未来出现）内的原生 `<button>` 需 `:where(.claude-msg-pane, .claude-msg-portal) button { background-color: transparent }` 防御 UA ButtonFace 随 color-scheme 翻转出中灰条（tailwind.gen.css 无 preflight）。

## 关联文件

core/dashboard/static/src/global.less（变量组）、pages/projects/components/{RunRecordModal,SpecTimeline}.tsx、pages/activities/components/AdminRunModal.tsx、pages/activities/components/ChainPanel.tsx（--fenix-chain-* 横线双档：深 #545557/浅 #f1f5f9）
