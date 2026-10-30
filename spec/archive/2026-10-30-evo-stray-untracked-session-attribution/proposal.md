# Proposal：stray-untracked-session-attribution

## 背景

主树散件盘点器对 tracked WIP 与 untracked 散件双流判据不对称：tracked 流经 identify_wip_occupant 做会话归因（core/worktree_manager/stray_wip.py:454-500），归因到活跃交互会话即复位计时、降级 info 留痕、不派 major；untracked 流（_untracked_signal，:657-755）全程无归因探测，一律按无主散件走「建档计时→30 分钟宽限→滞留 24h 或 500MB 升级 major→admin 处置归档」。交互会话常驻主树、手工起草 spec 是常规动作，untracked WIP 与真散件在管线中不可区分。该缺口系已归档 spec evo-add-maintree-interactive-session-attribution 显式挂账（「untracked 散件盲区另案处理」）无承接；越阈场景有真实先例（admin-potplayer-base-1791485794：90 文件/486MB 归档，MANIFEST 证明交互会话在场抢先处置属常态）。

## 目标

1. untracked 流越阈后接入既有会话归因器：归因命中即复位宽限计时、降级 info 留痕，不升级。
2. 豁免语义对齐 tracked 流：复位时钟而非永久豁免，会话离场后宽限重新起算。
3. 升级信号 evidence 注记归因探测已执行/零命中，让 admin 处置侧能判读。

## 非目标

- 不建 mtime 交集基建（daemon 无「会话近期写文件」数据源，核实不可行）。
- 不建显式认领清单 .fenix/stray_claims.json（外部会话无自然写入方，机制会空转腐化）。
- 不低于阈值时调归因（无告警风险的集合不付子进程探测成本）。
- 不做 spec/changes/ 路径特判白名单（归因判据自身已要求路径相关性，路径白名单反给真散件留借道口）。

## 方案概要

_untracked_signal 增参 running_run_ids，在越阈分支宽限判定前调用 identify_wip_occupant：命中会话归因且 admin.maintree_session_attribution_action != keep 时 pop 计时条目+info 留痕+返回 session-attributed；_sweep_locked 调用点透传。全部复用既有构件（归因器、配置键、日志口径），零新状态文件。