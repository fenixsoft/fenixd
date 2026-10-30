# 对话视图 harness 品牌投影

<!-- knowledge: capability=harness-brand-projection rev=1
     sources=spec/archive/2026-10-30-add-harness-brand-projection -->

运行记录对话组件族（claude-msg）的品牌解耦：消息头标签与头像图标按 run 的 harness 投影——dsh run 显示 dsh 品牌，claude run 显示不变，新 harness 不再错标。

## 规则

- **品牌经 context 外部投影**：消息头标签与头像图标经 `HarnessBrand` context（`{ name, Logo }`）取得；组件内 MUST NOT 出现字面 `'Claude'` 标签或无条件 `ClaudeLogo` 渲染；context 缺省值为 Claude 品牌——未注入 Provider 的使用点行为与单 harness 时代一致。
- **run 维度按 harness 注入**：run 视图（`RunRecordModal`/`AdminRunModal`）从 run meta 读取 `harness` 字段并注入对应品牌。harness 运行时真相源 = run_metrics 旁路行的新增 `harness` 键：runner 以该 run 派发时确定的 adapter.name 写入——取值来自 run 自身上下文，MUST NOT 读进程级当前 adapter（进程级全局在并发 run 收尾会串号）；未装配 adapter 的提前终态路径省略该键；dashboard 数据层把它索引进 run meta。harness 字段禁塞进 run jsonl canon（真相源走 run_metrics 旁路行，run jsonl 保持 claude stream-json 形状）。
- **回退链**：run meta 无 harness 字段（存量 run）回退 claude 品牌；harness 值无注册品牌（如 `pi`）回退首字母徽标（圆形底 + 大写首字母）+ 原值标签，MUST NOT 抛错白屏。
- **dsh 官方图标**：`DshLogo` 以官方资产渲染（源自 deepseek.com/harness/favicon.svg，MIT 项目官方品牌资产），填充固化基础品牌蓝 `#4D6BFE` 且 MUST NOT 携带 `prefers-color-scheme` 媒体查询——dashboard 固定浅色主题，OS 暗色偏好的白色变体在浅色界面同色消失（应用引入暗色主题时再恢复自适应）；`aria-label="dsh"`。
- **豁免与边界**：自由会话 `SessionPanel` 为 claude 专用车道、不注入（缺省品牌即正确）；不做 provider 级品牌映射（bigmodel/deepseek 网关不做图标——harness 才是对话 agent 身份）；组件文件名（ClaudeOutputPane 等）属历史包袱不强制改，耦合消除在内容层。

## 溯源

- 2026-10-30 add-harness-brand-projection（spec/archive/2026-10-30-add-harness-brand-projection） — 新增本能力：HarnessBrand context 外部投影与 Claude 缺省、run_metrics harness 键真相源（run 自身上下文取值防并发串号）、无字段/未知值双级回退链、DshLogo 官方资产固化品牌蓝并去暗色媒体查询
