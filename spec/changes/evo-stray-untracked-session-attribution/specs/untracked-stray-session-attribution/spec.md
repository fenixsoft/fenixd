# spec：untracked-stray-session-attribution

## 能力

主树 untracked 散件管线在越阈后具备会话归因探测能力：活跃交互会话在写的 untracked 文件豁免升级处置，宽限计时随归因状态复位。

## 需求

### R1 越阈归因探测

- _untracked_signal 在通过告警阈值判定后（进入宽限/升级判定前）调用 identify_wip_occupant，与 tracked 流同一归因器、同一判据（近窗提交路径交/活跃 transcript 路径提及）。
- 归因器输出三态（在飞实现车道 holder / 主树会话归因 / 零命中），三态均须有约定处置（见 R2），MUST NOT 留未定义态。
- 低于阈值时不调用归因器（零子进程开销）。

### R2 归因豁免行为

- 命中会话归因且 admin.maintree_session_attribution_action != keep 时：pop 该指纹计时条目（宽限时钟复位）、落一条 info 留痕（口径与 tracked 流一致）、本轮不进入宽限告警与升级判定，返回状态标 session-attributed。
- 命中在飞实现车道 holder（非会话归因）时：同样 pop 计时、不告警、本轮不进入宽限/升级判定，返回状态标 holder-attributed（对齐 tracked 流 holder 分支「归属期间不算滞留」语义）。
- 配置为 keep 时完全回退现状行为（照常计时）。
- 豁免是时钟复位而非永久豁免：归因消失（会话离场、路径不再提及）后重新建档计时。

### R3 升级 evidence 注记

- 升级 major 信号的 evidence 追加归因探测结果注记，措辞按探测结果分档，供 admin 处置侧判读；对齐 tracked 流告警的归因证据段形态。零命中写「归因探测已执行，零命中（判据：近窗提交路径交/活跃 transcript 路径提及）」；命中但配置 keep 回退写「归因探测已执行，命中但配置 keep 回退（视同零命中）」，MUST NOT 误述为零命中。

### R4 约束

- 不新增 AdminStore signal_type、不新增状态文件。
- 归因判据保守性沿用既有红线：仅「存在活跃会话」不得单独构成命中，须路径相关性证据。
- tracked 流行为零改动。

## 验收

1. 越阈集合中含活跃会话在写的 untracked 文件：该指纹被复位、无 stale/escalated 信号、info 留痕在案。
2. 越阈集合命中在飞实现车道 holder：该指纹被复位、无告警、状态标 holder-attributed。
3. keep 配置下同集合照常走宽限/升级（现状回归）；若探测命中会话归因，升级 evidence 注记写明「命中但配置 keep 回退」而非「零命中」。
4. 零命中集合照常走宽限/升级，升级 evidence 含「归因探测已执行/零命中」注记。
5. 低于阈值集合不触发归因器调用（stub 计数断言）。
6. tests/test_maintree_stray_wip_sweep.py、tests/test_stray_whitelist_untracked.py 既有用例回归通过。