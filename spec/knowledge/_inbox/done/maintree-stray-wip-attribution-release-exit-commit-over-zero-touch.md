# 主树散件 WIP「归因解除退场遗留」形态：commit 正解而非零触碰（maintree-stray-wip-sweep 判据补充）

## 背景

2026-11-26 maintree_stray_wip_stale 升级（指纹 c74e6c9db0f75832，2 文件
core/dashboard/routes/static_routes.py + core/dashboard/static/src/locales/en-US.ts，
admin run 1795735580 处置）。既有能力页把「dsh web 会话直改」定性为结构性盲区
噪音、处置终态一律零触碰 resolved，其判据是「归属者事后自行提交自愈」。本例
同处盲区形态，但该判据被证伪，零触碰不再是正解。

## 结论（当前事实）

- 盲区噪音形态（零触碰正解）的成立前提是「归属会话仍活跃、事后自愈」。当
  daemon 日志出现 worktree_manager 的「主树散件 WIP 会话归因解除」行、随后按
  无主重建档升级时，意味着归属会话已退场且未提交——自愈不会来，零触碰只会
  让散件无限滞留。
- 退场遗留散件若同时满足：(a) diff 内容完整自洽（注释自述动因、与既有 API
  与键位兼容）；(b) 正在挡在飞车道（WIP overlap precheck 反复 blocked、批保留
  待合回）——处置正解是裁决选项 commit_stray_wip，前置做 import 链闭合与
  hunk 重叠预检（清单内 tracked 文件 import 的 untracked 组件、以及与被挡
  分支同文件 hunk 是否文本重叠，均须实测）。
- 机械归因的「归因解除」日志行是判别「活跃盲区」vs「退场遗留」的关键锚点。
  告警 evidence 只带当刻归因结论、不带历史命中轨迹，处置方 MUST 主动对账
  daemon 日志取归因时间线，不能只按 evidence 的「无主」字面处置。
- mtime 同纳秒批量是 autostash pop 重写特征（对账「Stash popped after merge」
  日志行秒级吻合即实锤），不构成「刚编辑过＝会话还活跃」的证据；内容指纹
  计时不受影响（ADR-257 口径）。
- 首发型（evidence 无复发注记）+ 上述退场遗留判据成立时，commit_stray_wip
  是 sanctioned 口径；untrack_stray_wip 对源码/文档清单仍属仓库损伤，不适用。

## 证据

- daemon 日志（.fenix/logs/fenixd.log）归因时间线：11-26 09:54Z 起归因命中
  「主树活交互会话（会话=icyfenix <test@fenix.local>，
  信号=recent-commit-path-intersection）」info 降级留痕，持续约 12h（每小时
  聚合行「近 1h 重复归因 60 次」）；21:57:22Z 归因解除行；22:54:26Z 按无主
  重建档；23:24:36Z 宽限耗尽升级。
- mtime 重写实锤：两文件 mtime 同纳秒 2026-11-27 05:46:24.608 +0800，与
  21:46:24.675Z「Stash popped after merge」日志秒级吻合（pop 先写文件、70ms
  后落日志）；21:21:27Z/21:45:51Z 两次「Autostashed tracked changes before
  merge」证明该 WIP 在 pop 前已存在。
- 挡车道实锤：22:21/22:57/23:26 三次「Merge-back blocked by WIP overlap
  precheck (policy=escalate)」（fenix/code-review-fix-1795729590 与
  fenix/code-review-fix-1795731978，code-fix 批保留待自动合回）。
- 预检实测：static_routes.py:339 `_send_file(self, path, ctype,
  cache="no-cache", ...)` HEAD 即有 cache 形参；WIP hunk（en-US.ts:803
  totalSpecsPrefix ''→'Total '）与两分支 hunks（623/1271/1286/1306 行新增
  settings.evolution/projects.detail 键）零文本重叠。
- 处置：choice_id=commit_stray_wip，两文件入库后散件盘点自动复位、被挡批
  下一轮合回自动放行。
