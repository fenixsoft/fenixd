# judge「转纯归因保持 testing」终态即无驱动悬置成因

## 背景

2026-11-11 orphaned_state 处置（admin run admin-redesign-chain-panel-ui-1794373315，spec redesign-chain-panel-ui）：judge 车道跑完裁决轮后 spec 在 testing 态无驱动悬置 18 分钟触发孤儿探测。

## 结论

- judge 车道以「修复预算已耗尽（无修复纯归因模式）——拒收 scenario-repaired 申报，场景文件不改写、不重入执行，转纯归因（test-defect 仅记录），保持 testing」收尾时，**车道不再调度任何后续驱动**（不重验入队、不派发、不升级），spec 从此悬置在 testing 态；隐式续接依赖 orphaned_state 探测（约 15 分钟）+ Administrator 零动作 resolved 处置走复位直通道（分支已合并 → transition_gate(testing) 幂等 + 清 error + verifier 重验入队）。这是设计内挂起但无主动续接的时序缺口，属已知兜底路径而非 daemon 故障——处置时无需重启、无需手动 reset。
- 该形态的鉴别特征：spec error 字段为上述「修复预算已耗尽…保持 testing」文案 + `_judge_rerun_count` 触顶 + judge run 已归档 + verify-progress mtime 停在 judge 轮结束时刻。命中即零动作写 resolved 结案，勿开启新诊断分支。
- 多项目宿主上多个 `fenixd.py` 进程共存属正常（各项目独立 supervisor 子进程），排除「异项目 daemon 混淆」用 `readlink /proc/<pid>/cwd` 鉴别；本 spec 的进程内 verifier 线程判据只看主树 daemon（cwd=/root/fenixd）的 `/proc/<pid>/task/*/comm`。

## 证据

- fenixd.log 2026-11-11T04:37:35Z→04:44:25Z：verify_engine 全量 22 场景起跑 → planner-judge 成功（9 rounds）→ pm_engine「'redesign-chain-panel-ui' 修复预算已耗尽，转纯归因 — 拒收 judge scenario-repaired 申报」→ 4 场景裁决映射强制重写 fail→failed(test-defect) → 04:47 run 归档，之后无任何派发条目。
- `git merge-base --is-ancestor fenix/redesign-chain-panel-ui-1794325386 main` exit=0（分支已合并，复位走重验分支）。
- 处置记录：.fenix/admin_disposition-admin-redesign-chain-panel-ui-1794373315.json
