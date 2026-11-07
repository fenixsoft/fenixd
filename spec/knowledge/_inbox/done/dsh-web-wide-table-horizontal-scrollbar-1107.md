# dsh web 对话框横向滚动条：wide 表 bleed 公式 × 全宽模式变量失同步

- 日期：2026-11-07
- 现象：会话中宽表格（如「FenixName column flex」消息下的参数表）渲染后，对话框出现横向滚动条（仅部分表格触发）。
- 结论层级：fenix-dsh-chat-polish 插件缺陷（已修），dsh core 公式退化路径（未报上游）。

## 机制链（真相源）

1. **触发类**：dsh-client-ui-primitives `lib/index.js:11420` `clsx(markdownCss.tableScroll, wide ? "md-table-wide" : markdownCss.tableFill)`——表格自然宽超过内容宽（680px 基准）即注入 `md-table-wide`；窄表走 `tableFill`+`overflow-x:auto` 自滚，不出问题。
2. **wide 表对称出血公式**（`@deepseek-ai/dsh-client-ui-primitives/lib/markdown/MarkdownText.module.css`，打包于 `dsh-web-frontend/dist/assets/index-BPHePDI_.css`）：
   ```css
   .hWmORq_body .md-table-wide {
     --dsh-table-spare: max(0px, calc((100cqw - var(--dsh-chat-content-width)) / 2));
     --dsh-table-lead: calc(var(--dsh-table-spare) + min(var(--dsh-chat-content-width), 100cqw) - 100%);
     width: calc(100% + var(--dsh-table-lead) + var(--dsh-table-spare));
     margin-left: calc(-1 * var(--dsh-table-lead));
     padding-left: var(--dsh-table-lead);
   }
   ```
   设计假设列宽 = `--dsh-chat-content-width`（核心默认 `clamp(680px, calc(1000px*.64), 920px)` = **680px**），lead≥0 时负 margin 左溢 + padding 左补偿实现对称出血。**公式无下限**：lead 可解析为负。
3. **失同步**：fenix-dsh-chat-polish 全宽对话覆盖（client.js POLISH_CSS）把 `.EvIC1a_column{max-width:none}` 放宽到实际 940px（scroll 容器 cqw 988 − 24px×2 侧距），但 `--dsh-chat-content-width` 仍是 680px → 公式按 680 列 + 130px 侧边余量求值，而 `100%`（margin 上下文按包含块 940 解析）→ lead = 130+680−940 = **−130px** → `margin-left: calc(-1×−130) = +130px` 右推。
4. **溢出传播**：包装器左缘 +130、右缘 1070 > 列 940；溢出沿 `overflow-x:visible` 链（`_markdown_`→`hWmORq_body/root`→`flowItem`→`column`）直达 `EvIC1a_scroll`（仅 `overflow-y:auto`，`container-type:inline-size`，是 cqw 来源）→ 对话框级横向滚动条（sw 1094 > cw 988）。

## 排查手法（可复用）

- playwright-cli 持久会话（`-s=debug`，`--browser=chrome`）；旧消息要点 "Load earlier" 分页才进 DOM。
- 变量解析值探针：往目标元素 append 临时子元素 `margin-left: var(--dsh-table-lead)` 读计算值；cqw 容器沿祖先找 `container-type:inline-size`。
- 归属定位：遍历 `document.styleSheets` 找含目标类/变量的 `cssRules`，再 grep dsh-bundle 与 dsh-plugins 定位源文件。
- 活站修复验证：注入临时 `<style>` 测算，验完移除（本次共验三种假设：lead 加 floor → 不够（width 右出血项仍在）；同步变量 → 够；变量同步 + margin 夹紧 → 完美）。

## 修复（fenix-dsh-chat-polish client.js POLISH_CSS，HMR 即时生效）

```css
/* 全宽模式同步变量为实际列宽 */
body:not(:has(.wSkVaW_embeddedBody)) [data-conversation-scroll] .hWmORq_root{--dsh-chat-content-width:calc(100cqw - 48px)}
/* 公式退化路径仍有 spare 右出血 24px 正 margin，min(0px,…) 只夹右推、保留向左出血 */
.hWmORq_body .md-table-wide.md-table-wide{margin-left:min(0px, calc(-1 * var(--dsh-table-lead)))}
```
- 作用域挂 `.hWmORq_root`（markdown 根）而非 `.EvIC1a_scroll`：用户气泡（`.Sixlwa_userStack` 等）也消费该变量，避免波及。
- 双类 `.md-table-wide.md-table-wide` 抬特异性压过核心同选择器规则，不用 `!important`。
- 终验（viewport 1280，干净态无探针）：margin-left 0、表格左缘与正文对齐（0/921，940 列内）、`dialogOverflow: false`。
- 残留：若 dsh 升级改哈希类（hWmORq_/EvIC1a_/wSkVaW_），规则失配自动失效，回官方布局（插件既有约定）。

## 坐标

- 插件：`/root/dsh-plugins/fenix-dsh-chat-polish/client.js`（POLISH_CSS 数组，约 L53-64）
- dsh CSS 源：`/root/fenixd/dsh-bundle/node_modules/@deepseek-ai/dsh-client-ui-primitives/lib/markdown/MarkdownText.module.css`（L208-217 hover 内滚；`.hWmORq_body .md-table-wide` 规则在打包 CSS）
- wide/fill 分流：`/root/fenixd/dsh-bundle/node_modules/@deepseek-ai/dsh-client-ui-primitives/lib/index.js:11420`
