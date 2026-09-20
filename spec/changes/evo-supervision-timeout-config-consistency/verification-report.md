# 验证报告：evo-supervision-timeout-config-consistency

> ⚠️ 本报告由框架于 2026-09-17T20:47:10Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-17T20:47:10.105594+00:00

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.74M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| supervision-floor-derived-values | 单一派生函数数值正确性：运行时基础档 15000+2×1800=18600s、fast-track higher 档 15000+4×1800=22200s、配置校验层全部署最大下限 max(全局,overrides)+4×1800=22200s（含 overrides 参与派生、显式 budget 优先、enabled=false/缺段跳过、生效值与一致时直通）。执行 tests/test_supervision_timeout_consistency.py::TestDerivedFloorValues（用例定义出处：tests/test_supervision_timeout_consistency.py:97-160，派生实现出处 core/config.py supervision_floor/supervision_config_floor） | pass | 0/11 | - |
| supervision-shared-derivation-single-source | config 校验层与 liveness 兜底层调用同一派生实现：liveness deadline 兜底经 supervision_floor 派生（spy 断言同一函数调用，基础档 18600s、fast-track higher 档 22200s）、无手写常数残留（SUPERVISION_EXTENSION_SECONDS 已删除、liveness floor_absolute_max 手写表达式已删除）、SUPERVISION_DEFAULTS 单源 re-export。执行 tests/test_supervision_timeout_consistency.py::TestSharedDerivation（用例出处 tests/test_supervision_timeout_consistency.py:164-236；liveness 改动出处 core/agent_runner/liveness.py:777-789 改调 supervision_floor） | pass | 0/5 | - |
| supervision-startup-auto-align | 启动一致性校验默认自动对齐：absolute_max(14400) < 配置校验层下限(22200) 时 ERROR 留痕（含两侧值 14400/22200 与修正建议文案）、内存抬升至 22200、不抛异常（启动可继续）；对齐记录供 daemon 持久化消费即复位；一致（absolute_max==22200）时无 ERROR、显式值生效。执行 tests/test_supervision_timeout_consistency.py::TestConsistencyCheck 自动对齐分支（用例出处 tests/test_supervision_timeout_consistency.py:239-266；校验接入出处 core/config.py _validate + fenixd.py:213 resolve_config） | pass | 0/4 | - |
| supervision-startup-fail-fast | 显式关闭自动对齐时启动 fail-fast：resolve_config 抛 ValueError（消息含 auto_align 与修正建议，启动失败）；严格 load 路径同 fail-fast；enabled=false 时即使 absolute_max 偏低也不对齐不阻断（校验跳过）。执行 tests/test_supervision_timeout_consistency.py::TestConsistencyCheck 阻断分支（用例出处 tests/test_supervision_timeout_consistency.py:269-307；fail-fast 语义出处 core/config.py _validate） | pass | 0/4 | - |
| supervision-hot-reload-align-persist | 热更新不一致默认自动对齐并持久化：文件改为 14400 后经 _maybe_reload_config 加载，内存抬升至 22200、对齐经既有写路径落盘（config.yaml 磁盘值=22200）、对齐 ERROR 留痕（含 14400/22200/修正建议）、再次热更新不再出现对齐 ERROR（消除同文案 ERROR 复发）。执行 tests/test_supervision_timeout_consistency.py::test_hot_reload_aligns_persists_then_silent（用例出处 tests/test_supervision_timeout_consistency.py:331-369；热更新接入出处 fenixd.py:645 resolve_config_into + config_admin.py write_config 受管键持久化） | pass | 0/2 | - |
| supervision-hot-reload-reject-rollback | 热更新关闭对齐时拒绝新配置并保留旧值：文件改为 14400+auto_align=false 后 fail-fast（ValueError 被主循环 try/except 捕获、daemon 不退出），resolve_config_into 失败不触碰旧 dict，共享 config 保持旧值 22200。执行 tests/test_supervision_timeout_consistency.py::test_hot_reload_rejected_and_rolls_back（用例出处 tests/test_supervision_timeout_consistency.py:371-405；回滚语义出处 fenixd.py:512-515 try/except + config.py:252-264） | pass | 0/2 | - |
| supervision-new-suite-full-pass | 新测试文件全量闸门：tests/test_supervision_timeout_consistency.py 全部 22 用例通过，覆盖派生数值/单一实现/自动对齐/fail-fast/热更新全功能面（tasks 2.1-2.4）。真实输出取证：22 passed, 3 warnings in 0.81s | pass | 0/2 | - |
| regression-runtime-floor-values | 既有运行时 floor 数值回归：TestSupervisionAbsoluteMaxFloor 三分支（override-raises-floor=10800 抬升、global-floor-no-raise=7200 不抬升、floor-covers-budget=7200 短 run 不误杀）保持既有语义，证明本次改动运行时封顶数值不变（用例出处 tests/test_run_lifecycle_hardening.py:549-618，断言依赖运行时基础档预算；真实输出取证 3 passed） | pass | 0/4 | - |
| regression-governance-decision-matrix | 监督运行时决策矩阵回归：TestSupervisionDeadlineAction 8 用例（绝对封顶无条件终止 12600、disabled 纯墙钟 kill、续期预算耗尽终止、零事件窗口 kill、advancing 续期、stagnant 终止留证、缺省激活、旧顶层键回退）全部通过，证明监督决策矩阵未被改动（用例出处 tests/test_run_lifecycle_governance.py:1090-1170；真实输出取证 8 passed） | pass | 0/9 | - |
| regression-config-settings-suite | config 校验层与系统设置配置回归：tests/test_config.py（54 passed）+ tests/test_system_settings_config.py（16 passed）合并 70 passed，证明 _validate 改动未破坏既有配置校验/系统设置读写（tasks 2.5；真实输出取证：70 passed, 14 subtests passed in 0.34s） | pass | 0/2 | - |
| regression-liveness-discrimination | liveness 活性判别回归：tests/test_liveness_hang_discrimination.py 10 用例全通过（实质/心跳区分、零实质事件 kill、负重复比不引入等），证明 liveness 改动仅替换派生口径、未改变判别行为（tasks 2.5；真实输出取证：10 passed in 0.05s） | pass | 0/2 | - |
| template-alignment-constraint-doc | 模板配置对齐约束文档：.fenix/config.template.yaml 的 timeout_supervision 段（agents 下）注释含对齐约束（absolute_max_seconds MUST ≥ max(全局 run_timeout_seconds, agents.timeout_overrides 全部值) + (max_extensions + 2) × extension_seconds）与示例值 16200（=9000 运行 + 4×1800 续期）、auto_align 处置说明完整；顶层回退段（:258）同样对齐（enabled: false + 16200）。出处 .fenix/config.template.yaml:106-120 与 :260-272；示例值可解析取证：template absolute_max_seconds = 16200 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景

