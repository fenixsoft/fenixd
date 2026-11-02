# 提案：散件升级证据体量预算与处置失败限次重派

## 背景

maintree_untracked_stray_escalated 升级信号（evo-stray-untracked-escalation 交付）把 evidence 全文内联进 Administrator 提示词。2026-10-24 主树出现 51054 项/895MB 的 node_modules 备份散件集合，升级信号 evidence 达 6,667,709 字符——其中「条目体积(字节)」段 6,664,081 字符全量逐项内联、无任何截断（core/worktree_manager/stray_wip.py:2077-2078，2026-10-30 评审勘误行号；文件清单段反而早有头部 50 项截断 :314-321），处置 run admin-fenixd-1792880308 首轮即被 API 400 prompt_too_long 拒绝（7.4 秒、1 轮、0 工具调用、0 美元）。死后无重派、无失败升级信号，告警悬空约 46 小时直至散件被带外清理；6.6MB 证据同时污染 admin_alerts.json（单行）、daemon 日志（单行 6.6MB 连推三轮轮转）与面板渲染三个存储面。

## 问题

- 升级信号 evidence 构造无总体量预算：体积明细段逐项 path=bytes 全量内联，集合体量过阈值（500MB）时必然撑爆处置提示词。
- Administrator 提示词装配侧（core/agent_runner/prompt_builder.py:488-507，{evidence} 于 :499；2026-10-30 勘误行号）对 evidence 无防御性上限。
- Administrator 处置 run 死于 prompt_too_long/api_error 终态时无兜底重派：该终态由 admin worker 落账为 final failed 处置组（core/admin_monitor.py:6650-6689），孤儿巡检走 `_converge_final_orphan_group`（:5594）而非 interrupted 分支（:5355），现有 interrupted 形态限次重派通道（:5355-5399）不覆盖；且 daemon 级散件信号存在 spec 记法关联失配（SIGNAL 记录 spec=None、处置组记录 spec=<项目名>，`unhandled_signal_for` 严格相等恒不命中）——2026-10-24 事故组实查仅 pending+final failed 两条、零 ESCALATION，孤儿收敛升级同样被此失配静默致盲（46h 悬空根因）。

## 目标

1. 体积明细段套用与文件清单段同型的头部 N 项截断＋「等 N 项」＋体积合计聚合；全量体积引用注册表单源（sizes_bytes），不在 evidence 内联。
2. Administrator 信号注入侧加防御性体量上限：超限 fail-open 截断并附注记，保证提示词长度有界。
3. 处置 run 死于 prompt_too_long/api 400 终态时自动限次重派（复用 reschedule_max），重派携带瘦身 evidence，且重派/升级关联判定对 daemon 级散件信号（spec=None vs 项目名失配形态）可达；限次用尽产生处置失败升级信号（critical ESCALATION 人工介入出口，不进入派发失败自动重试扫描，避免突破 reschedule_max 总额形成重派风暴）。
4. 契约测试钉住「万项级清单信号不得撑爆处置提示词」。

## 非目标

- 不改升级触发阈值与归因探测语义（在飞 evo-stray-untracked-escalation / evo-stray-untracked-session-attribution 范围）。
- 不追查本案散件集合被带外清理的主体。

## 方案概述

core/worktree_manager/stray_wip.py 体积明细段复用 EVIDENCE_MANIFEST_PREVIEW_LIMIT 同型上限（头部 50 项＋合计字节）；core/agent_runner/prompt_builder.py administrator 分支注入前体量检查（fail-open 截断）；core/admin_monitor.py 在孤儿处置恢复巡检内把 prompt_too_long/api 400 final failed 终态纳入与 interrupted 同型的限次重派通道（同步修复 daemon 级散件信号 spec 记法关联失配），重派传递瘦身 evidence，限次用尽落 critical ESCALATION 人工升级。
