# 验证报告：evo-add-maintree-interactive-session-attribution

> ⚠️ 本报告由框架于 2026-10-03T20:48:43Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-03T20:48:43.077862+00:00+run-result@mtime1791060523123124079

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.68M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| attribution-zero-hit-failopen-sweep | 探测源缺失/零命中时盘点走既有无主宽限升级路径（行为与现状逐位一致）：合成身份夹具仓（HEAD 提交人与任何环境 git 身份相异、无 worktree 车道、无会话信号）注入主树 tracked 散件，grace=30 首轮盘点应 orphan-timed 且零告警；grace=0 二轮（独立 sweeper 实例）应 alerted 且 maintree_stray_wip_stale major 恰一条；前后 git status --porcelain 逐字节一致（零触碰）。出处：spec specs/maintree-wip-attribution/spec.md『Scenario: 探测源缺失或零命中』；现状行为锚点 core/worktree_manager/stray_wip.py:44-65（grace 配置守卫）、:168-253（_sweep_locked 无主建档/宽限升级）、:255-267（_fingerprint） | pass | 0/6 | - |
| attribution-zero-hit-identify-contract | identify_wip_occupant 零命中分支 API 契约与现状逐位一致（会话探测零命中 fail-open）：合成身份夹具仓注入散件后以 G4+G8 mixin 探针壳直调 identify_wip_occupant(['a.tsx'], [])，应 holder=false、holders 空、describe 含『无主』自认、overlap 原样回传，识别全程主树 status 逐字节不变（只读不写，mergeback.py:952 约束）。出处：spec『Scenario: 探测源缺失或零命中』；tasks 1.1『零命中/源缺失时行为与现状逐位一致』；现状锚点 core/worktree_manager/mergeback.py:856-935（识别入口）、core/worktree_manager/types.py:27（BLIND_SPOT_NOTE）、:74-96（describe） | pass | 0/6 | - |
| lane-attribution-priority-unchanged | 在飞实现车道命中优先于会话探测、既有行为不回退：夹具仓建 impl-spec-x-1700000000 worktree （分支 fenix/spec-x-1700000000 提交对 a.tsx 的改动）+ 主树 a.tsx 散件，sweep 传入在飞 run_id 应判 holder（status=holder）、零 major 告警、status 形态不为会话归因新形态——会话探测只在车道归因零命中后追加，不得抢占既有归因结果。出处：spec『Requirement: 主树活交互会话归因源』WHEN 子句『车道归因零命中时』；现状锚点 core/worktree_manager/mergeback.py:847-853（_INFLIGHT_LANE_RUN_PREFIXES）、tests/test_maintree_stray_wip_sweep.py:283（test_holder_hit_no_timing_no_alert 既有口径） | pass | 0/4 | - |
| session-attributed-downgrade-info-by-default | 主树活交互会话直改归因命中→盘点默认降级 info 留痕、不派 major（核心正向路径）：夹具仓以环境 git 身份（global 身份同步写入 repo-local config，双读法都一致）在近窗提交 touch a.tsx （design 决策 1 候选②『最近提交人启发：HEAD 作者与项目配置身份一致＋近窗提交＋散件路径与最近提交集有交』全条件），再留 a.tsx 散件；identify 应 holder=true（会话归因线索、非无主），缺省配置（不设 maintree_session_attribution_action）sweep 的 status 必须落在四既有值（clean/holder/alerted/orphan-timed）之外的新会话归因形态，且 maintree_stray_wip_stale major 为 0 条。注：探测源实现取材是 design 留给实现者的取舍，本夹具按候选②最通用读法构造，若实现只取候选③等源导致零命中，失败证据（id_holder/id_describe）供裁决定位。出处：spec『Scenario: 活交互会话直改主树』；tasks 2.1『status 新增会话归因形态』『不派 maintree_stray_wip_stale major』；design 决策 1/3 | pass | 0/5 | - |
| session-attributed-config-keep-fallback | 配置 admin.maintree_session_attribution_action=keep 时会话归因散件回退现状宽限升级路径：同一会话夹具（环境身份近窗提交 touch a.tsx + 散件），config 显式 keep 且 grace=0，sweep 应视同零命中走无主升级——status=alerted 且 major 恰一条（与无主散件同一升级路径，归因仍产出会话线索 id_holder=true 但盘点侧不放行降级）。出处：spec『Scenario: 配置回退』；tasks 2.1『keep=现状行为』；design 决策 3 | pass | 0/4 | - |
| session-attributed-config-invalid-guards-to-keep | 配置 admin.maintree_session_attribution_action 非法值时守卫回退 keep（保守方向，配置事故不得静默吞 major）：同一会话夹具，config action='bogus' 且 grace=0，sweep 应按 keep 处置——status=alerted 且 major 恰一条；若实现误把非法值当 info 降级则本场景失败。出处：tasks 2.1『配置非法值守卫回退 keep（保守方向：配置事故 MUST NOT 静默吞 major，对齐 grace_minutes 守卫哲学）』；守卫现状锚点 core/worktree_manager/stray_wip.py:47-65 | pass | 0/4 | - |
| new-testsuite-exists-and-passes | 新归因测试套件存在且全绿：tasks 交付物 tests/test_maintree_interactive_session_attribution.py 落盘并以 pytest -v --tb=short 全部通过（覆盖探测命中/零命中/源缺失三分支、WipOccupantInfo 会话形态与 describe 文案、stray_wip 降级与配置回退、code_fix 透传）。出处：tasks 3.1（交付物与覆盖面清单）；spec『Requirement: 主树活交互会话归因源』全场景 | pass | 0/3 | - |
| new-testsuite-covers-normative-surfaces | 新套件覆盖面锚定规范符号（防『测试文件存在但未覆盖规范面』的空壳）：测试文件内容必须引用规范配置键 maintree_session_attribution_action（tasks 2.1 规范键名）、归因入口 identify_wip_occupant（tasks 1.1）、消费者模块 code_fix（tasks 2.2/3.1 透传覆盖）。出处：tasks 2.1/2.2/3.1 的规范性命名与覆盖要求 | pass | 0/5 | - |
| legacy-suites-no-regression | 两份既有测试文件全绿且用例数不缩水（tasks 3.2『既有用例全部不回退』）：tests/test_maintree_stray_wip_sweep.py（基线 14 用例）与 tests/test_mergeback_wip_coordination.py（基线 19 用例，identify_wip_occupant 直接测试场）pytest -v 全过；ast 计数探针断言两文件 test_ 用例数不低于基线（防删用例凑绿）；并抽查四条归因核心既有用例逐名 PASSED。出处：tasks 3.2；基线数实测于本仓现状（ast 统计 14/19） | pass | 0/8 | - |
| consumers-adjacent-regression | 归因消费者相邻面回归全绿：code_fix WIP 预检（tests/test_code_fix_wip_precheck.py）、worktree WIP artifact 范围（tests/test_worktree_wip_artifact_scope.py）、merge-back 冲突打捞（tests/test_code_fix_mergeback_conflict_salvage.py）三文件 pytest 全过——code_fix.py/stray_wip.py 改动不得波及消费侧相邻行为。出处：tasks 2.2（code_fix 消费点改动面）；三文件现状实测 50 passed | pass | 0/2 | - |
