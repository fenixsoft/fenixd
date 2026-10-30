# 验证报告：evo-ignore-receiver-debug-artifacts

> ⚠️ 本报告由框架于 2026-10-11T19:30:46Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-11T19:30:45.315694+00:00+run-result@mtime1791747045346580262

## 结论：✅ 通过（verified）

**状态：verified — 6/6 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 6/6 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.42M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| gitignore-debug-entry-with-chinese-comment | .gitignore 追加 .debug/ 目录条目且带中文注释：条目行形如 .debug/（容忍 **/.debug/ 变体），条目上方 6 行内存在含中文的 # 注释且注释提及 receiver/接收器落点（tasks.md 1.1，spec Requirement「调试产物目录 ignore 豁免」；D3 注释风格对齐先例 build-win-configure.log/tailwind.gen.css 条目）；既有 ignore 条目（.history/、dist/、.fenix/*、claude-msg/tailwind.gen.css）原样保留——追加不得覆写既有内容。出处：仓库根 .gitignore（现 30 行、末条 151ff6e 先例）、spec/changes/evo-ignore-receiver-debug-artifacts/tasks.md:9 | pass | 0/9 | - |
| check-ignore-hits-debug-dir-and-not-overbroad | git check-ignore -v 对 .debug/ 根目录及会话子目录深层路径均命中新追加条目，输出含 .gitignore:<行号>: 规则源（spec Scenario「check-ignore 命中」——命中来源必须是交付的 .gitignore，排除 .git/info/exclude 或全局 excludes 蒙混）；对照路径 z-ignore-control-probe-file 不被任何规则命中——豁免不外溢（机械判据出处 core/worktree_manager/stray_wip.py:676 porcelain -uall 不列 ignored、:692-693 仅无规则命中路径计入散件）。check-ignore 按路径求值无需目录真实存在。 | pass | 0/7 | - |
| porcelain-excludes-debug-artifacts | 模拟 receiver 真机调试产物（3 个会话子目录 × 3 文件 = 9 个 dump-*.png / receiver-<pid>.log，复刻主树 .debug/ 真实形态）落入验证树后，git status --porcelain -uall 对 .debug/ 路径零输出（spec Scenario「porcelain 零输出」）；同批落地的对照散件 z-ignore-control-probe-file 仍被列出——证明 porcelain 通道本身有效、豁免并非空转（防假阴性）。幂等自播种，场景间顺序无关。 | pass | 0/6 | - |
| stray-sweep-collector-immune-to-debug-dir | 散件巡检面整体免疫（spec Requirement「散件巡检面整体免疫」）：以交付仓库真实判定器 core/worktree_manager/stray_wip.py 的 _untracked_stray_entries（:640，porcelain -uall + check-ignore 批量复核）对含 .debug/ 产物的验证树实测收集——断言散件清单不含任何 .debug/ 路径、仍含对照散件（巡检通道非空转）；收集后 9 个模拟产物原路径原样存在（巡检零触碰契约，现场零扰动）。「指纹消失→注册表自动复位」由该机制因果保障（指纹源=散件路径集，清单已空即指纹消失；_reset_registry_absent 为既有框架行为），daemon 300s 盘点周期与注册表落盘属主树运行时行为，不在 fresh 验证实例复现范围——spec Scenario「指纹复位」的触发前提由本场景机械化验证。 | pass | 0/8 | - |
| new-debug-session-writes-stay-ignored | 后续调试会话持续写入不受影响（spec Requirement「现场零扰动」后半：「MUST NOT 影响接收器后续调试会话继续写入该目录」）：模拟新会话 session-4 落地 dump-0042.png / receiver-9999.log，check-ignore 命中新路径、porcelain 对 .debug/ 仍零输出，既有 9 个产物原样保留——D1 目录级条目覆盖全部未来会话（会话子目录与 dump-*/receiver-<pid> 文件名均为动态形态，逐文件 glob 无法覆盖）。 | pass | 0/11 | - |
| delivery-no-delete-rename-outside-spec | 变更面回归（design Non-Goals「不改散件管线代码与阈值」；spec Scenario「升级已先触发的收口」的「以既有 admin 裁决 ignore_untracked_stray 收口、不重复建设」在 fresh 验证实例的机械化对应＝变更面仅 .gitignore 一处）：以 git merge-base HEAD main（回退 origin/main）为基准，① diff --diff-filter=DR（delete/rename，一提交形态覆盖已提交+未提交态）在排除 spec/ 归档移动后必须为空——不得删除/改名任何既有文件（现场零扰动的 git 层对映）；② core/ 产品代码零改动——散件管线（core/worktree_manager/stray_wip.py）与告警阈值不得被顺手修改。BASE 缺失时输出诊断标记并显式失败。 | pass | 0/4 | - |
