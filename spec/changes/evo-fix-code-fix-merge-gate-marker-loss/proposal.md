# 提案：code-fix 合并门纯标记提交保全

## Why

code-fix 车道的合并门以 fixed=0 一票拒绝整批合回，把批次里「纯 fenix-ignore 误报标记」的提交一并丢弃：2026-11-14 session-advanced-search 修复链两条拒合回（dsh-plugins 项目实例日志 /root/dsh-plugins/.fenix/logs/fenixd.log 11:40:04Z/11:47:34Z，fixed=0, commits=1）弃掉 979f47f、00162a0 两个纯标记提交。源内标记是防同一误报下轮复发重烧修复轮（约 $1.5-2/轮）的唯一跨轮抑制手段——条目指向的源文件已被架构转向删除、指纹去重对新报失效，审查侧注入约定（core/agent_runner/maintenance_runs.py:4832 `OCR_IGNORE_MARKER_BACKGROUND` 常量，2026-11-16 实测；「就近有标记 MUST NOT 再上报」）全靠标记兑现；标记进 main 的现役唯一通道是搭 fixed 批便车（9e284e5 先例），纯标记批无任何合回通道。弃件同时零持久留痕（仅计数 warning 日志、无 commit id、无告警）：10-19 同门弃件（run code-fix-1792430442）的提交内容因 id 未落任何持久面已永久不可考。且 run 终态在合并裁决前记 success（core/agent_runner/runner.py:10640），-6417 收尾自述「commit 00162a0 已落」与产物实际被弃直接矛盾——fixer、runner、合并门三层对产物去向认知互不一致。同门跨日弃件在档可考至少 4 起（10-14 16:22Z commits=1 一起内容未考、10-19 一起内容不明已永久不可考、11-14×2 纯标记），系统性缺口非一次性失误。

## What Changes

- **纯标记提交放行（core/code_fix.py 零有效修复守卫）**：fixed=0 且 commits>0 时不再一律拒合回——先对批内提交做形态核查（新增行全部为 fenix-ignore 标记注释形态），纯标记批直接合回并按完成收尾；混合批（含非标记改动）维持拒合回但 MUST 留痕全部 commit id 与非标记文件清单。
- **全批 ignored 收尾路径同治**：fixed=0 且全批 ignored 的「批按完成收尾」分支（现记 success 直接清理、不合回，core/code_fix.py :7924-7934 一带，2026-11-16 实测）同样先执行纯标记核查与合回再收尾，不再静默丢弃。
- **弃件强制留痕**：拒合回发生时 MUST 落一条含全部被弃 commit 完整 SHA、批条目 id、非标记文件清单的告警记录（admin store），落痕先于 worktree 清理；现有 warning 日志文案同步附 commit id。
- **产物去向进批级终态**：链收尾 rollup 与台账注记区分「产物已合并（纯标记）/产物已弃（附 commit id）」，消除三层矛盾；runner 层 run_metrics 发出时点与语义不动。

## Capabilities

- `specs/code-fix-merge-gate/spec.md` — ADDED：code-fix 合并门纯标记提交放行与弃件留证

## Impact

- **受影响模块**：`core/code_fix.py`（零有效修复守卫，2026-11-16 实测 :7923；全批 ignored 收尾分支 :7924-7934；弃件留痕告警；链 rollup 注记）；新增测试 `tests/test_code_fix_marker_only_merge.py`。
- **兼容性**：fixed>0 批合回、commits=0 零产物批拒合回（10-16 形态 11 起）、可修复形态 salvage（`_salvage_stranded_batch` 调用点 :7910 一带）三路径行为零变化。
- **存量捞回**：本窗两弃件 979f47f14686…/00162a099da2… 仍为悬空对象（2026-11-16 实测位于 dsh-plugins 项目仓 /root/dsh-plugins 对象库、不在任何分支上；fenixd 主仓检索不到），gc 前可人工 cherry-pick 捞回——属 dsh-plugins 主树人工步骤（登记 .fenix/todo.md），不入本 SPEC 任务书（主树只读纪律）。
- **无 UI、无数据迁移、无配置键**。