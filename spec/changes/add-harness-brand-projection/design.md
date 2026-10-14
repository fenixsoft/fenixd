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
2. **harness 真相源 = run_metrics 旁路行新增 `harness` 键**（runner 在 `_log_run_metrics` 处从当前 adapter 取 `adapter.name`）：run_metrics 是 fenixd 自有格式（ADR 边界内可扩展），不碰 run jsonl canon；runs.py 索引 run meta 时透出。备选「投影层塞 claude 形状 result 的 model 字段」被否——model 字段语义是网关模型名（成本页在用 provider_marker 的 model），混入 harness 名会破坏成本匹配。
3. **回退链**：run meta 无 harness 字段（存量 run）→ claude；harness 值无注册品牌 → 首字母徽标（圆形底 + 大写首字母），不崩。
4. **dsh 图标用官方 favicon SVG**（`assets/dsh-mark.svg` 副本入库组件目录）：官方品牌资产（MIT 项目）、自带 `prefers-color-scheme` 明暗自适应；以 React 组件 `DshLogo` 包裹（dangerouslySetInnerHTML 或内联 path），`aria-label="dsh"`。
5. **注入点 = run 弹窗/视图层**：`RunRecordModal` 与 `AdminRunModal` 从 run meta 读 harness 包 Provider；SessionPanel 不注入（豁免，Non-Goals）。

## Risks / Trade-offs

- [存量 run 无 harness 字段被误标 claude] → 可接受：存量 run 本就多为 claude；dsh 存量 run 数量有限且证据在 run jsonl 可查。
- [run_metrics 消费方对新增键敏感] → 该行是结构化 JSON 日志，消费方（runs.py 索引、延迟分析脚本）按键取值，新增键向后兼容。
- [SVG 内嵌 style 的 media query 在组件化后失效] → 保留 `<style>` 原样内联（浏览器对内联 SVG 的 media query 生效）；冒烟验证明暗两态。

## Migration Plan

纯增量：无字段回退 claude 保证存量行为零变化；dsh 标注自新 run_metrics 行起生效。回滚 = revert。

## Open Questions

（无。）
