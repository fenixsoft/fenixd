# 提案：maintree-stray-wip-sweep（主树散件 WIP 周期盘点与滞留升级）

## Why

fenix 常驻 daemon 对流水线外产生的主树未提交改动（散件）存在检测盲区：2026-10-03 复核实例中，被分析项目主树 4 个 tracked 源文件（25+/15-，mingw/Windows 可移植性修复）在 spec done 后滞留工作树超 6 小时无人认领（git status 实测仍 M；`git log e6d3e1e..HEAD -- <4 文件>` 为空；run 档案 18 条末事件均无可归属的在飞实现）。机制根因有三，均已核实：

1. autostash 使散件对合回闸门不可见：merge-back 走「autostash→merge→pop」（fenixd.log:1096 "Autostashed tracked changes before merge"），主树被先行腾空，add-mergeback-wip-active-coordination 的 WIP overlap 占用者识别/无主升级全程不触发；副作用是该次 pop 还批量重写了改动文件 mtime（四文件纳秒级同刻 02:22:13.233），销毁了滞留时长的直接证据。
2. 周期巡检刻意不碰也不报告：`core/worktree_manager/stash_guard.py:591 reclaim_stale_autostash` 明确「主树 tracked 脏说明用户正在工作，不抢」——保护语义正确，但缺少配套的报告出口。
3. 无任何周期性主树 dirty 盘点：`grep -rn 'dirty|uncommitted' core/` 仅命中 knowledge 模块自身记账；本次实际检出靠 daily self-review 复盘车道（LLM run，滞后约 4 小时 46 分），属高成本低时效的偶然检出。

代价：散件无限期滞留、暴露于人工清理丢失风险、且每次检出都要消耗一次复盘 run；框架「无人值守」前提下，环境态异常（主树长期 dirty）应当由机械巡检以分钟级时效、告警级成本浮出。

## What Changes

新增一个周期性只读盘点车道：daemon 主循环既有巡检点旁挂接 sweep——盘点主树 tracked 未提交改动，按「路径集 + diff 内容哈希」指纹计时（不用 mtime，实证其被 autostash 覆写），复用 `WipOccupantInfo` 对在飞实现车道做机械归因；无主且宽限耗尽时经 AdminStore 发一次性 major 告警 `maintree_stray_wip_stale`（附文件清单、first_seen、盲区注记、提交/stash 处置指引）。全程零触碰：不 stash、不 checkout、不 clean、不 reset。

## Capabilities

- maintree-stray-wip-sweep（新增）

## Impact

- 涉及：`core/worktree_manager/`（新增 sweep 模块）、`fenixd.py`（主循环接线）、`core/admin_monitor.py`（信号登记）、新增单测。
- 复用：`core/worktree_manager/types.py`（WipOccupantInfo + BLIND_SPOT_NOTE）、`core/code_fix.py` `_write_defer_orphan_alert` 告警型、`core/worktree_manager/stash_guard.py` 主树锁纪律。
- 不改变：merge-back/pre-dispatch autostash 既有路径、reclaim_stale_autostash「脏不抢」语义、WIP overlap 既有闸门。