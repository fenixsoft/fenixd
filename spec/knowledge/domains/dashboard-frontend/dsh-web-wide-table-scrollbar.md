# dsh web 对话框宽表横向滚动与全宽变量同步

<!-- knowledge: capability=dsh-web-wide-table-scrollbar rev=1
     sources=spec/knowledge/_inbox/done/dsh-web-wide-table-horizontal-scrollbar-1107.md -->

dsh web 会话对话框内 markdown 宽表格的横向滚动治理：dsh core 的 wide 表对称出血公式行为、fenix-dsh-chat-polish 全宽模式下的变量同步义务，以及排查与修复验证配方。

## 规则

- **宽窄分流**：dsh-client-ui-primitives（`lib/index.js` 的 wide/fill 三元）按表格自然宽与内容宽基准（680px）分流——超宽表注入 `md-table-wide`；窄表走 `tableFill` + `overflow-x:auto` 自滚。对话框级横向滚动条问题只出现在 wide 分支。
- **wide 表对称出血公式无下限**：`.md-table-wide` 以 `--dsh-table-lead`（左溢量）+ `--dsh-table-spare`（侧边余量）求负 margin 左溢 + padding 左补偿，实现左右对称出血；公式假设列宽恒等于 `--dsh-chat-content-width`（dsh core 默认 `clamp(680px, calc(1000px*.64), 920px)` 即 680px）。公式对 lead 无下限保护，lead 可解析为负值——这是 dsh core 侧缺陷，当前未报上游，以插件侧补偿治理。
- **全宽覆盖必须同步列宽变量**：chat-polish 全宽对话覆盖把列放宽到实际约 940px（scroll 容器 988 − 24px×2 侧距）时，必须同步 `--dsh-chat-content-width: calc(100cqw - 48px)`。只放宽列宽不同步变量时，公式仍按 680px 列 + 130px 侧边余量求值，而 `100%` 按实际 940px 包含块解析 → lead 变负（−130px）→ `margin-left` 由负翻正右推 → 表格右缘超出列宽 → 溢出沿 `overflow-x:visible` 链（markdown 根/body → flowItem → column）直达滚动容器（仅 `overflow-y:auto`、`container-type:inline-size`，亦是 cqw 来源）→ 对话框级横向滚动条。
- **退化路径 margin 夹紧**：变量同步后公式退化路径仍残留 spare 右出血（约 24px 正 margin），以 `margin-left:min(0px, calc(-1 * var(--dsh-table-lead)))` 夹紧——只压右推、保留向左出血。双类 `.md-table-wide.md-table-wide` 抬特异性压过 core 同选择器规则，不用 `!important`。
- **变量作用域挂 markdown 根**：变量覆盖挂在 `.hWmORq_root`（markdown 根）而非滚动容器——用户气泡（`.Sixlwa_userStack` 等）同样消费该变量，挂在容器会波及非目标面。
- **哈希类失配自动回退**：修复规则锚定 dsh 打包哈希类（hWmORq_/EvIC1a_/wSkVaW_）；dsh 升级改哈希类后规则失配自动失效，回退官方布局（插件既有约定，不视为故障）。
- **修复通道**：修复落在 fenix-dsh-chat-polish 插件 `client.js` 的 POLISH_CSS 数组，HMR 即时生效；禁改 dsh dist 打包产物。

## 关键行为

- **变量解析值探针**：往目标元素 append 临时子元素 `margin-left: var(--dsh-table-lead)` 读计算值；cqw 容器沿祖先找 `container-type:inline-size`（滚动容器既是溢出终点也是 cqw 来源）。
- **归属定位**：遍历 `document.styleSheets` 找含目标类/变量的 `cssRules`，再 grep `dsh-bundle` 与 `dsh-plugins` 定位源文件——CSS 公式源在 `@deepseek-ai/dsh-client-ui-primitives/lib/markdown/MarkdownText.module.css`。
- **活站假设验证**：注入临时 `<style>` 逐假设测算，验完移除；多假设对比定案（本症三假设：lead 加 floor 不够——width 右出血项仍在；变量同步——够；变量同步 + margin 夹紧——完美）。
- **终验口径**：干净态（无探针残留）下 margin-left 为 0、表格左缘与正文对齐、对话框无横向溢出。
- 会话内取证用 playwright-cli 持久命名会话（`-s` 隔离）；旧消息需点 "Load earlier" 分页后才进 DOM。

## 溯源

- 2026-11-07 dsh-web-wide-table-horizontal-scrollbar-1107（spec/knowledge/_inbox/done/dsh-web-wide-table-horizontal-scrollbar-1107.md） — 新增本能力：wide/fill 分流与对称出血公式机制链（无下限缺陷）、全宽覆盖列宽变量同步义务与溢出传播链、退化路径 margin 夹紧与作用域纪律、哈希类失配自动回退约定、变量探针/样式表归属/活站假设验证配方与干净态终验口径
