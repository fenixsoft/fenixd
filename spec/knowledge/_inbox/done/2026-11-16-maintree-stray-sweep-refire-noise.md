# maintree_stray_wip_stale 同指纹再升级噪音与 commit 断链反证（2026-11-16）

## 背景

第 7 次 admin 处置同型 maintree_stray_wip_stale 误报（指纹 ceaeb0b387e2e5d4，6 文件 dashboard 图标钮改版+配置深链）发现两条 maintree-stray-wip-sweep 页尚未记载的增量事实，投递供 distill 折叠。

## 结论（当前事实）

- **同指纹「归因出现→消失」转换会重置计时再升级**：同指纹 ceaeb0b387e2e5d4 于 07:13Z 被前一轮 admin 零触碰处置后，07:18Z 新 dsh web 会话（pid 2810267）出现使归因命中、清计时；会话退场后归因消失轮以 first_seen=07:24:24Z 重新起算，宽限耗尽 07:54Z 同指纹再升级（同 daemon boot 内）。同指纹一次性去重对「归因命中清计时→消失重起算」路径不设防——活跃 dsh 工作流期间会话每开合一次就烧一条 admin run。建议：归因再命中后的消失轮继承原 first_seen，或升级标记（同指纹已升级过）在归因清计时时保留、仅内容指纹变化才清除。
- **commit_stray_wip 断链反证**：信号清单只含 tracked 6 文件，而 `list.tsx` import 的 `@/components/DshIconButton` 与 `tests/specListConfigButton.test.mjs` 均 untracked 不在清单内——对含 untracked 新组件依赖的改动集执行 commit_stray_wip 必产生 HEAD 断链提交（verify 链/新 worktree 播种即坏）。清单约束守卫防的是越界，防不了这种「清单内自洽、清单外断链」形态；处置方核验 import 链是必要前置。
- **处置终态复证**：第 7 度仍零触碰 + 显式跟踪项收口（resolved），源码 diff 注释自述用户需求 + 归属者自投递收件箱文件（点名全部文件+自检 481/481）为强归属实锤；同型告警 5 轮历史全部归属者自行提交自愈。

## 证据

- 处置记录：.fenix/admin_disposition-admin-fenixd-1794815708.json（2026-11-16，本 run）
- 记忆文件：fenixd-admin-maintree-stray-wip-disposition（本指纹第 6 度条目 07:13:50Z 更新在前、本告警 first_seen 07:24:24Z 在后，再升级时序实锤）
- ps：dsh web 1680665（Nov15 起）、dsh --profile web 2810267（07:18Z 起）与 first_seen 重置时刻对齐

## 更新目标页（distill 时）

`spec/knowledge/domains/worktree-vc/maintree-stray-wip-sweep.md`（rev=6→7：复发噪音段补「归因转换再升级」子形态与去重不设防点；裁决选项段补 commit_stray_wip 断链反证）；`maintree-wip-attribution.md` 若有归因清计时语义段一并校对。
