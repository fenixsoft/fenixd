# Proposal: code-fix 选批前 WIP 重叠预检

## 问题背景

2026-09-23 深夜 code-fix 车道第 21/22 批在合回时才被 WIP 重叠预检拦下（主树 QualityTab.tsx 与 projects/detail.tsx 的未提交改动与批次分支重叠），当时唯一处置是「现场即弃」，已完成并通过回归的整批工作作废（第 21 批还多烧了一轮完整回归）。fix-codefix-wipgate-defer 已落地事后 defer 降损（保留现场、只补 merge），但选批环节仍会把与主树 WIP 重叠的条目选进批次——烧掉整批 agent run 与回归后才在 merge-time 拦下。

## 方案概述

CodeFixExecutor.checkpoint 在选批后、批任务投递前增加预检：

1. 取主树 dirty tracked 文件集合（复用 core/worktree_manager/stash_guard.py 的 _list_dirty_tracked_files）。
2. 与候选批条目的 file 字段求交，并按 merge-time 闸门同款产物判别排除 dist 类产物路径。
3. 命中即整批推迟：写 progress（running=False, phase=blocked, reason=wip_overlap_at_select，附交集文件文案）并返回未触发，不置单飞、不投递批 worker；下轮节拍自然重查，把冲突消在实现之前。

## 影响范围

- 修改 core/code_fix.py：checkpoint 选批预检与推迟出口
- 新增 tests/test_code_fix_wip_precheck.py：预检回归

## 非目标

- 不做主树 WIP 的 autostash/自动提交——WIP 属人工/UI 会话产物，框架侧不可强制（「及时提交或 stash」是人工运维约定）。
- 不改变 merge-time 闸门与 defer 路径——预检只覆盖台账 file 字段与脏文件的交集，agent 实际改动超出条目 file 时仍靠 merge-time 兜底。
