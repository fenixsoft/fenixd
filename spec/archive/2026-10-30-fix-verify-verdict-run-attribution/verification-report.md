# 验证报告：fix-verify-verdict-run-attribution

> ⚠️ 本报告由框架于 2026-10-27T08:03:12Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-27T08:03:10.901897+00:00+run-result@mtime1793088190951564447

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.15M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dispatch-stamp-overwrites-old-residue | 派发侧归属戳·正向路径：spec 处 testing 态时向派发队列入队 verifier 并驱动真实出队分支，预置的前一轮 plan-ready 残留（add-command-center 事故形态）被原子改写为三键归属戳 {role:verifier, spec, status:dispatched}，旧残留不复存在。对应 tasks 1.1 / spec.md「派发预写覆盖旧残留」；出处 core/pm_engine/dispatch/queue.py:1423-1427（「Dispatching」日志点即预写锚位）、core/pm_engine/verification/report_gate.py:373-383（primary 路径单源）。夹具驱动方式与 tests/test_verifier_dispatch_reverify_lane.py:33-48 同构。 | pass | 0/2 | - |
| dispatch-stamp-write-failure-does-not-block | 派发侧归属戳·异常路径：归属戳写入遇 OSError（夹具把 verify-progress/<spec> 置为普通文件注入，root 下 chmod 不拦写故用路径形态注入）时，派发流程照常继续（verifier 正常出队派发），且日志落 WARNING 留痕、不阻断派发。对应 tasks 1.1 / spec.md「预写失败不阻断」。 | pass | 0/2 | - |
| dispatch-stamp-covers-prior-verdict-residue | 派发侧归属戳·跨 run 判定残留覆盖：预置上一轮 verifier 真实写出的 bug-found 裁决（含 run_id/bugs 完整判定内容），新一轮 verify 派发时同样被三键戳整体覆盖，旧判定内容（bug-found/bugs）不残留——防「旧判定重放到当前轮次 = 假 bug-found/假 verified」。对应 proposal What·派发侧归属戳；出处 core/pm_engine/verification/legacy.py:453-463（陈旧/异 spec 判定重放护栏语义）。 | pass | 0/2 | - |
| fresh-agent-verdict-without-role-accepted | 消费侧归属校验·分支①采信正向路径：agent 直写的无 role 戳新鲜 primary 裁决（status=verified、spec 戳匹配、mtime 晚于 run_id 内嵌 epoch）被照既有口径采信——spec 晋级 verified/done、触发晋级回调，MUST NOT 因无 role/run_id 戳被判「本轮无裁决」或误归档（primary 豁免 role 门，judge_gate D3 教训不回退）。对应 tasks 2.1/2.2② / spec.md「agent 正常写出的新鲜裁决被采信」；出处 core/pm_engine/verification/report_gate.py:493-517（_read_verdict primary 直接采信）。夹具与 tests/test_verdict_contamination.py:248-268 同判据。 | pass | 0/2 | - |
| dispatched-stamp-consumed-as-no-verdict-produced | 消费侧归属校验·分支②本轮未产出裁决：verify 完成时共享文件仍为派发预写戳原样（role=verifier、status=dispatched）→ 判「本轮未产出裁决」走 fail-closed：spec blocked + critical 升级告警，文案指明「本轮未产出机器可读裁决」；MUST NOT 出现 stale/foreign replayed 归因、MUST NOT 自动重派入队、不回拨 implemented。对应 tasks 2.1/2.2① / spec.md「agent 未落裁决（预写戳原样）」。 | pass | 0/2 | - |
| stale-residue-archived-fail-closed-report-preserved | 消费侧归属校验·分支③残留处置+成果保全主链：陈旧 plan-ready 残留（mtime 早于本轮派发时刻）→ 先归档 .fenix-run-result.json.stale-<ts> 备份（内容与残留逐字一致，保留法证现场）→ 再按「本轮无裁决」fail-closed（blocked + critical 告警指明「本轮未产出机器可读裁决」）；同时新鲜 report.json（mtime ≥ 派发时刻，run_id 内嵌 epoch 判据）被重命名保全为 report-<run_id>.json 且 WARNING/告警文案附保全路径，MUST NOT 静默丢弃当轮验证成果、MUST NOT 出现 replayed 归因、MUST NOT 自动整轮重派。这是 add-command-center 事故（39 分钟×2 验证成果被当重放作废）的直接回归锚。对应 tasks 2.1/2.2③/3.1 / spec.md「跨 run 残留不再作废当轮成果」+「新鲜 report 强制保全」。 | pass | 0/2 | - |
| no-fresh-report-no-preservation | 成果保全·负向路径两态：①report.json 不存在、②report.json 存在但 mtime 早于本轮派发时刻（run_id 内嵌 epoch 判据）——两种情形均 MUST NOT 产生 report-<run_id>.json 保全文件，fail-closed 处置（blocked + .stale-<ts> 归档）照既有路径进行。对应 tasks 3.1/3.2② / spec.md「无新鲜 report 不保全」。 | pass | 0/2 | - |
| fresh-plan-ready-keeps-testing-channel | 消费侧归属校验·in-chain planner 既有通道回归：本轮派发窗口内写出的新鲜 plan-ready（mtime 新鲜于 run_id epoch）不属残留——照既有「验证未完成」通道处置：保持 testing 待重验、error 留「验证未完成」痕；MUST NOT 判 fail-closed blocked、MUST NOT 升级 critical 告警、MUST NOT 归档覆盖 planner 当轮产物（.stale-<ts> 不出现、产物内容原样）。对应 tasks 2.3 前态 / spec.md「新鲜 plan-ready 照既有通道」；出处 core/pm_engine/verification/legacy.py:760-787（plan-ready/scenario-repaired 不按通过收口分支）。 | pass | 0/2 | - |
| foreign-spec-stamp-residue-archived-fail-closed | 消费侧归属校验·分支③异 spec 戳残留：其它 spec 的 verified 裁决落在本 spec primary 路径（status 白名单内但 spec 戳不符）→ 归档 .fenix-run-result.json.stale-<ts> 备份 + fail-closed（blocked），不采信为当轮裁决、无 replayed 归因、不自动重派、无 report 保全（无本轮 report）。对应 tasks 2.1 分支③ / spec.md Requirement 分支③「异 spec 戳残留」；出处 core/pm_engine/verification/report_gate.py:174-191（_verifier_stamp_gate foreign-stamp 判据）。 | pass | 0/2 | - |
| unit-tests-verdict-run-attribution-pass | 交付物单测回归：tasks.md 新建单测文件 tests/test_verdict_run_attribution.py 存在且全绿（承载 tasks 1.2/2.2/3.2 要求的三态单测：派发戳覆盖/写入失败不阻断、消费三态、保全两态）。pytest -q 断言 exit_code=0 且输出含 passed 摘要；文件缺失时 pytest 退出码非 0 即失败。 | pass | 0/3 | - |
| regression-verdict-contract-singularity-green | 既有契约回归（tasks 4.1）：tests/test_verdict_contract_singularity.py 全绿——verdict 单点契约、role/spec 戳回退语义（_verifier_stamp_gate 单源）不因本 SPEC 改动回归。 | pass | 0/2 | - |
| regression-verifier-dispatch-lane-green | 派发车道回归：core/pm_engine/dispatch/queue.py 是本 SPEC 修改文件（tasks 1.1 在 verifier 出队分支插预写点），tests/test_verifier_dispatch_reverify_lane.py 全绿锚定派发闸门行为不回归——testing/implemented 态 verifier 照常派发、非法态仍被守卫拦截、预写点插入不破坏单飞守卫与槽位记账。 | pass | 0/2 | - |
