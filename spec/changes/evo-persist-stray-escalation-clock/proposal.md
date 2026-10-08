# persist-stray-escalation-clock

## 背景

potplayer-base 主树 90+ 个验证证据散件滞留多日、maintree_untracked_stray_stale 告警 34 次零处置，且证据两次被整包入库（c91213f、6f1042e），HEAD 树 verify-evidence/ 已达 689MB。回源核实发现框架侧三项机制已先行合并：evo-add-verify-evidence-placement-contract（缺省落位 .fenix/verify-evidence/{spec}）、evo-verify-evidence-tiered-retention（max_binary_bytes 缺省 10MB + sha256 sidecar）、evo-stray-untracked-escalation（major 升级 + archive/ignore/delete 三裁决）。但机制实际未闭环，残余缺陷有二：

1. 升级时钟被 daemon 重启击穿：/root/fenixd/core/worktree_manager/stray_wip.py:202 的 _untracked_registry 为纯内存 dict 无持久化，restart_history.jsonl 现存 3 条重启记录（2026-10-07/08）且每条告警 first_seen 都落在重启后约 70 秒——24 小时滞留升级（elapsed≥1440 分钟）在重启间隔最长约 11 小时的现状下永不触发，escalated 信号至今 0 条，「同指纹一次性告警」也被击穿成重复 4 条。
2. 项目侧未接线：potplayer-base 的 .fenix/verify.yaml 未声明 evidence_retention，活跃 spec tasks.md 仍有 7 处路径指向根 verify-evidence/，存量未跟踪 485MB 散件未清债。

## 目标

1. 未跟踪散件盘点注册表落盘持久化：daemon 重启后恢复 first_seen 与指纹，24 小时滞留升级与体积升级跨重启连续计时，同指纹去重跨重启保持。
2. 项目侧收尾（一次性运维）：verify.yaml 接线 evidence_retention、活跃 tasks.md 落位路径改写、存量散件经已上线的裁决执行器清债。

## 非目标

- 不重建落位/留存/升级机制（三项已在飞或已合并）。
- 不自治重写 git 历史清除已入库的 689MB（需 filter-repo，属人类决策，至多在处置记录中留方案）。
- 不改 info 档 maintree_untracked_stray_stale 的「只告警不处置」语义（信息档定位如此，升级通道已存在）。
