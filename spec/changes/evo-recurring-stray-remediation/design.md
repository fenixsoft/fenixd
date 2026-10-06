## Context

检测面：core/worktree_manager/stray_wip.py（SIGNAL_TYPE :37，告警写点 _write_alert :700-722，现无复发计数、不引用历史处置）。裁决：core/dashboard/data/adjudication_choices.py maintree 桶 :292-294，唯一项 _COMMIT_STRAY_WIP :101-108（spec_scoped=False + signal_type 绑定守卫先例）。执行器：core/dashboard/data/admin_actions.py execute_adjudication_choice :2879（_exec_commit_stray_wip :2765 为首个主树 git 写执行器先例）。untrack 骨架：core/worktree_manager/stash_guard.py（_untrack_ignored_local_changes :1034、_untrack_index_paths :916、_purge_ignored_brought_in :1202，被「check-ignore 全须忽略」前置门挡住——目标生成物文件实测不被 ignore）。admin 契约：agents/administrator.md（裁决选项消费 :110、铁律区 :118，grep 散件/stray 零命中），经 core/agent_runner/prompt_builder.py:48 装载、core/agent_runner/maintenance_runs.py:252 构造。测试：tests/test_adjudication_choices.py:51,171-200（commit_stray_wip 注册/resolve/守卫）、tests/test_maintree_stray_wip_sweep.py（纯检测面）。实证案例：potplayer-base build-win-configure.log 两度处置（5935771/95a0c01），根治建议 10-04 已写明、10-06 原样复发。

## Goals / Non-Goals

- Goals：复发型散件有「当场根治」的一键路径与强制契约；告警自带复发计数使根治义务可判定；untrack 后同路径改动由 .gitignore 自然止损，检测面零改动。
- Non-Goals：不动检测触发逻辑；不做 stash/discard 项；不修改 stash_guard 既有前置门；不做跨仓自动执行（根治动作由 admin 处置车道在告警发生地执行）。

## Decisions

- D1 untrack 执行器独立实现、复用 stash_guard 的 staged 子集守卫/回滚子函数而非打开其「check-ignore 全须忽略」前置门：目标文件（生成物日志）本就不被 ignore，打开旧门会连带放开既有自愈路径的暴露面；独立执行器作用面限于告警指认文件清单，误伤面最小。
- D2 复发计数以 admin_alerts 同文件历史 maintree_stray_wip_stale 告警+处置记录为准，不另建台账文件；计数随告警 evidence 下发，使「第 2 次处置起必须根治」的义务在处置时点是可判定的，而非依赖 agent 自行考古。
- D3 根治义务挂 admin 契约铁律而非代码硬拦截：处置质量属 agent 判断域，代码侧保证「根治路径一键可达+复发可见」；与失效模式（「留给人类决策」在无人值守下永不到来）相反，无人在场时根治路径必须可一键执行，违反义务由下轮告警/复盘回收，先观察契约实效再考虑硬闸。
- D4 .gitignore 追加去重、untrack 与提交原子成一批独立提交（不与处置中其他改动混合），沿用 _exec_commit_stray_wip 的独立提交先例，保证可回滚。

## Risks / Trade-offs

- untrack 误摘「实为需共享的源件」会丢基线：以「告警指认清单为作用面+结果留痕+首次处置不强制根治」限定与缓冲，复发才触发义务，保留一次人工/agent 判断窗口。
- 契约铁律无代码拦截，理论上仍可能第三次仅提交：复发计数使违反可见，后续可按数据加硬闸；本 SPEC 先落路径与契约。
- 复发检索按文件路径匹配，文件改名后计数断档：可接受——改名后的文件本质是新敞口，从 1 重计不放大风险。