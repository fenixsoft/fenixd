## Context

多 harness 落地后（add-dsh-adapter-integration 已验收），运行记录的对话视图仍把所有 run 显示为 Claude。组件族 claude-msg 自 claudecodeui 迁移而来，身份耦合有两处：`MessageItem.tsx` 的 `headerLabelFor()` 恒返回 `'Claude'`（:54）与头像恒渲染 `ClaudeLogo`（:45）；`ClaudeLogo.tsx` 是 claude 官方 SVG。运行真相源在 runner：run_metrics 旁路行是 harness 无关的自有格式，当前未携带 harness 字段。

## Goals / Non-Goals

**Goals**
- 品牌名与图标经 context 外部投影，claude-msg 组件不再字面耦合 'Claude'。
- run 维度正确标注：dsh run 显示 dsh + 鲸鱼图标；claude run 不变。
- 官方 dsh 图标入库（明暗自适应）。

**Non-Goals**
- 组件文件改名（ClaudeOutputPane/ClaudeMessageList 等文件名保留，避免全仓 churn；文件名不是运行时显示）。
- run jsonl canon 改动（harness 真相源走 run_metrics 旁路行，不进 claude 形状 schema）。
- 自由会话 SessionPanel 品牌化（claude 专用车道，缺省品牌即正确）。
- provider 级品牌（bigmodel/deepseek 网关不做图标映射——harness 才是对话 agent 身份）。

## Decisions

1. **React context 注入而非 props 逐层传**：品牌对整棵消息树生效，props 会污染 MessageItem/ClaudeMessageList 的既有签名；context 缺省值 = `{ name: 'Claude', Logo: ClaudeLogo }`，未注入处行为与现状逐字节一致。
2. **harness 真相源 = run_metrics 旁路行新增 `harness` 键**（runner 在派发装配时把该 run 的 `adapter.name` 记入 run 自身上下文，`_log_run_metrics` 收尾从 run 自身上下文取值写入；MUST NOT 在收尾时刻读进程级 `get_current_adapter()`——`_current_adapter` 为进程级全局、重复注入以最后一次为准，并发 run 收尾会取到别的 run 的 adapter 串号；adapter 未装配的提前终态路径省略该键，读侧缺省 claude 兜底）：run_metrics 是 fenixd 自有格式（ADR 边界内可扩展），不碰 run jsonl canon；runs.py 索引 run meta 时透出。备选「投影层塞 claude 形状 result 的 model 字段」被否——model 字段语义是网关模型名（成本页在用 provider_marker 的 model），混入 harness 名会破坏成本匹配。
3. **回退链**：run meta 无 harness 字段（存量 run）→ claude；harness 值无注册品牌 → 首字母徽标（圆形底 + 大写首字母），不崩。
4. **dsh 图标用官方 favicon SVG**（`assets/dsh-mark.svg` 为源，内联进组件、不落独立资产文件）：官方品牌资产（MIT 项目）；内联时**固化基础品牌蓝 `#4D6BFE`、移除源资产的两条 `prefers-color-scheme` 媒体查询**——dashboard 当前固定浅色主题、无暗色切换能力，OS 暗色偏好在 Chrome/Firefox 会把图标切成白色变体（#fff），浅色界面上即同色消失；源资产注释自证基础品牌蓝在明暗背景均可见（Safari 即恒用基础蓝）。应用未来引入暗色主题时再恢复媒体查询。以 React 组件 `DshLogo` 包裹（内联 path/style），`aria-label="dsh"`。
5. **注入点 = run 弹窗/视图层**：run meta（含 harness）经 runs 列表 API 到达父级视图（`projects/detail.tsx` / `activities/index.tsx`），由父级经 props 把 harness 传入弹窗——两个 Modal 现仅持 runId/project、不持有 meta，须扩展 Modal props 并同步修改两个父级调用点（admin 车道 run 的 meta 经 run_activity 同口径透出）；SessionPanel 不注入（豁免，Non-Goals）。

## Risks / Trade-offs

- [存量 run 无 harness 字段被误标 claude] → 可接受：存量 run 本就多为 claude；dsh 存量 run 数量有限且证据在 run jsonl 可查。
- [run_metrics 消费方对新增键敏感] → 该行是结构化 JSON 日志，消费方（runs.py 索引、延迟分析脚本）按键取值，新增键向后兼容。
- [源资产 media query 在固定浅色应用下反成消失态：OS 暗色偏好命中 `prefers-color-scheme:dark`→#fff，浅色界面上同色消失] → 内联时移除媒体查询、固化基础品牌蓝 `#4D6BFE`（明暗背景均可见）；应用引入暗色主题时再恢复自适应。

## Migration Plan

纯增量：无字段回退 claude 保证存量行为零变化；dsh 标注自新 run_metrics 行起生效。回滚 = revert。

## Open Questions

（无。）
