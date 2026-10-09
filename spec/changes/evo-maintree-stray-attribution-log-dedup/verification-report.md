# 验证报告：evo-maintree-stray-attribution-log-dedup

> ⚠️ 本报告由框架于 2026-10-09T19:25:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-09T19:25:53.737597+00:00+run-result@mtime1791573953796175925

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.25M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| sweep-combined-suite-regression | 回归钉：两套交付测试全量通过——tests/test_maintree_stray_wip_sweep.py（32 例，含去重类 TestSessionAttributionLogDedup）与 tests/test_maintree_interactive_session_attribution.py（18 例，直接锁会话归因分支返回 status 契约，本改造不得破坏）。断言锚为实测输出（-v 单档，不并列 -q，防 pytest9 输出退化丢 PASSED）。出处：tasks.md 2.2；tests/test_maintree_stray_wip_sweep.py:821-926。 | pass | 0/6 | - |
| dedup-suite-six-cases-verdict | 交付用例逐点名：TestSessionAttributionLogDedup 全部 6 例 PASSED（R1 稳定静默/R2 小时聚合/R3 双迁移解除+闭环），覆盖 tasks.md 2.1 新增用例矩阵。用例名无 parametrize 后缀（已实测确认输出行形态）。出处：tests/test_maintree_stray_wip_sweep.py:821-926。 | pass | 0/8 | - |
| probe-r1-stable-attribution-single-log | R1 正向：同文件集同占用者连续 3 轮盘点，仅首轮落 1 条全量 info 留痕，后续轮静默且零 warning。探针以近窗提交作者=isess 触碰 a.tsx+主树散件装配真实会话归因现场（进程内驱动 MainTreeStrayWipSweeper，capture logger 收集日志），不复用交付测试文件。出处：core/worktree_manager/stray_wip.py:510-524（键=路径排序文件集+会话 identity，键变落全量行）。 | pass | 0/6 | - |
| probe-r1-fileset-change-new-full-line | R1 状态变化（文件集增员）：首轮留痕后散件新增 b.tsx，键（文件集维度）变化 → 恰落第 2 条全量行且含新文件名。出处：core/worktree_manager/stray_wip.py:510-518（文件集是键的一部分，集合变化触发新留痕）；design.md 边界「多文件并存」。 | pass | 0/6 | - |
| probe-r1-occupier-change-new-full-line | R1 状态变化（占用者变化）：仅改仓 email（name 不变仍与近窗提交作者匹配，归因保持）→ 会话 identity 变化 → 恰落第 2 条全量行。出处：core/worktree_manager/stray_wip.py:512（键第二维=占用者会话 identity）；tests/test_maintree_stray_wip_sweep.py:882-894 同款判定语义。 | pass | 0/5 | - |
| probe-r2-hour-window-aggregate-then-reset | R2 小时聚合：假时钟注入模块 time（仅替换 stray_wip.time 属性，真实驱动 now-ts>=3600 判定）——首轮全量行；+60s 稳定轮静默计数；+3601s 跨窗后恰落 1 条聚合行，文案含「近 1h 重复归因 2 次」（N=自上次留痕起含本轮的观测轮数）与文件名；窗口重置后再稳定轮零新增。聚合行文案实测自 core/worktree_manager/stray_wip.py:526-530。 | pass | 0/7 | - |
| probe-r3-release-on-files-gone | R3 解除（文件消失）：归因留痕后 checkout 还原 a.tsx → clean 轮恰落 1 条解除行（clean 早退到不了归因分支，解除判定先行于 448 行调用），再盘点一轮零重复（解除行不逐轮重写）。出处：core/worktree_manager/stray_wip.py:446-448、582-604。 | pass | 0/6 | - |
| probe-r3-release-occupier-cleared-reattribute-closure | R3 解除（占用者清空）+闭环：name/email 全改后零命中走无主宽限（orphan-timed），恰落 1 条解除行（holder 整体清空时归因分支不进入，解除判定单点在归因分支之前仍覆盖）；恢复原身份后再归因，键与解除前同值仍必须落新全量行（不被抑制计数吞掉，attr_lines=2）。出处：core/worktree_manager/stray_wip.py:480-486、594-604（R3 闭环）；tests/test_maintree_stray_wip_sweep.py:912-926 同款语义。 | pass | 0/7 | - |
| probe-r3-release-migrate-to-inflight-lane | R3 解除（归因迁至在飞车道）：会话归因留痕后建 worktree 分支 fenix/specx-1700000000 提交对 a.tsx 的改动并传入在飞 run_id → 归因迁至实现车道（is_session_attribution()=假，归因分支不进入）→ 恰落 1 条解除行且本轮 status=holder。出处：core/worktree_manager/stray_wip.py:480-486（迁移判定）；core/worktree_manager/mergeback.py:823-913（车道命中优先于会话探测）。 | pass | 0/6 | - |
| probe-r4-restart-state-loss-first-round | R4 重启丢状态：同仓新建第二个 sweeper 实例（模拟进程重启，去重状态为进程内内存态不持久化）→ 首轮按首次落全量行（fresh_attr_lines=1，允许一条重复，与 tracked 流 first_seen 内存态同一取舍）。出处：core/worktree_manager/stray_wip.py:286-290；spec R4。 | pass | 0/5 | - |
| probe-r4-info-level-and-adminstore-clean | R4 约束：连续 3 轮会话归因留痕期间 AdminStore 零新增记录（不派 major、不进人工队列）、capture logger 零 warning（日志级别维持 info，留痕行全走 info 通道）。出处：core/worktree_manager/stray_wip.py:496-524（降级 info 留痕、MUST NOT 新增 AdminStore signal_type）；spec R4。 | pass | 0/6 | - |
| probe-r4-keep-fallback-boundary-regression | 非目标边界回归钉：action=keep 回退态不进三态去重——散件按无主宽限升级（grace=0 首轮 alerted 恰 1 条 major、次轮 orphan-timed），去重全量行/聚合行/解除行均零落（dedup_full_lines=0、dedup_agg_lines=0），keep 回退说明行逐轮照旧 2 条（非目标不收敛）。预期锚为实测行为。出处：core/worktree_manager/stray_wip.py:496、541-546；proposal.md 非目标。 | pass | 0/7 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

