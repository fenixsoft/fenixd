# 主树 untracked 散件越阈会话归因豁免

<!-- knowledge: capability=untracked-stray-session-attribution rev=1
     sources=spec/archive/2026-10-30-evo-stray-untracked-session-attribution -->

主树 untracked 散件盘点在越阈后接入既有会话归因器：活跃交互会话或在飞实现车道在写的 untracked 文件豁免升级处置，宽限计时随归因状态复位——untracked 流与 tracked 流（[maintree-stray-wip-sweep](maintree-stray-wip-sweep.md)）归因判据对齐，交互会话在写的 WIP 不再被当无主散件升级。升级触发条件与认领执行器语义见 [stray-untracked-escalation](stray-untracked-escalation.md)。

## 规则

### 越阈归因探测

- untracked 盘点通过告警降噪门（越阈）后、进入宽限/升级判定前，调用 `identify_wip_occupant` 做归因探测——与 tracked 流同一归因器、同一判据（归因源全集与相关性门见 [maintree-wip-attribution](maintree-wip-attribution.md)）。
- 归因器输出三态（在飞实现车道 holder / 主树会话归因 / 零命中），三态均有约定处置，不留未定义态。
- 低于降噪门的集合不调用归因器：只建档计时，零子进程探测成本。

### 三态处置

- 会话归因命中且 `admin.maintree_session_attribution_action != keep`（缺省 info）：pop 该指纹计时条目（宽限时钟复位）、落一条 info 留痕（口径与 tracked 流一致）、本轮不进入宽限告警与升级判定，返回状态标 session-attributed。
- 在飞实现车道 holder 命中（非会话归因）：同样 pop 计时、不告警、本轮不进入宽限/升级判定，返回状态标 holder-attributed——对齐 tracked 流「归属期间不算滞留」语义，MUST NOT 视同零命中走宽限升级（否则会对仍在飞 run 名下的文件发射升级信号）。
- 零命中：维持现状流程（宽限 → 升级）。
- 配置为 `keep` 时完全回退现状行为：探测命中也照常计时走宽限/升级（与 tracked 流共用同一单键回退）。

### 豁免语义与升级 evidence 注记

- 豁免是时钟复位而非永久豁免：归因消失（会话离场、路径不再提及）后重新建档计时，first_seen 重新起算。
- 升级 major 信号的 evidence MUST 追加归因探测结果注记，措辞按探测结果分档，供 admin 处置侧判读：零命中写「归因探测已执行，零命中（判据：近窗提交路径交/活跃 transcript 路径提及）」；命中但配置 keep 回退写「归因探测已执行，命中但配置 keep 回退（视同零命中）」，MUST NOT 误述为零命中。

### 约束

- 不新增 AdminStore signal_type、不新增状态文件；升级信号登记与认领执行器语义不变。
- 归因判据保守红线沿用：仅「存在活跃会话」MUST NOT 单独构成命中，须路径相关性证据。
- tracked 流行为零改动。

## 溯源

- 2026-10-30 evo-stray-untracked-session-attribution（spec/archive/2026-10-30-evo-stray-untracked-session-attribution） — 新建本页：untracked 流越阈接入 `identify_wip_occupant` 三态归因（会话归因/holder 归因均复位宽限计时且当轮不升级，零命中维持升级流）、豁免=复位时钟而非永久豁免、升级 evidence 归因注记分档措辞（keep 回退不得误述零命中）、低于阈值零探测成本；回退单键与 tracked 流共用。
