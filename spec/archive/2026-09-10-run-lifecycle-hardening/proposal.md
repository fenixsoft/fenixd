## Why

2026-09-03 全天复盘暴露四类框架性浪费与卫生缺口：4 次自动归档全部留未提交变更（主树脏、origin 无归档记录、产物有丢失风险）；CLI 秒挂风暴 61 连发重试（Exit 143 不触发熔断、无退避），33 分钟空转至预算耗尽；`agents.run_timeout_seconds` 单值（9000s）套所有 agent 类型，planner-plan/judge 的合理上限远小于 implementer，2.5h 的 planner 场景设计被重启丢弃后连成本都无法核算；另有冻结语义覆盖不全、路径二义性、预算对账漂移三处卫生问题。

## What Changes

- **归档自动提交**：spec_done 的 push 流程（main-first 尾部）将 `spec/changes/` 的归档移动（删除 + archive/ 新增）一并 commit 并 push，归档产物闭环入库。
- **CLI 秒挂退避熔断**：同一 spec 连续秒级失败（进程存活 < 阈值秒数或 Exit 143 类瞬时死亡）≥3 次 → 该 spec 冷却 5 分钟不派发 + 发 major 告警；冷却结束自动恢复，无需人工。
- **run_timeout_seconds 按 agent_type 覆盖**：保留 `agents.run_timeout_seconds` 全局单源默认，新增 `agents.timeout_overrides.<agent_type>` 覆盖映射（如 planner-plan: 2700）；supervision 的 extension 总额与 absolute_max 派生、stuck 阈值派生均按覆盖后生效值联动；`liveness.py` 的 `JUDGE_TIMEOUT_SECONDS=120` 硬编码配置化（`agents.timeout_overrides.supervision-judge`，缺省回退 120）。
- **生命周期卫生**：verifier 阶段内部 failover 重试链尊重 frozen 冻结（attempt 重试前查 frozen 即停）；删除 `.fenix/STATE.md` 历史遗留空文件（真 STATE 在项目根，路径二义性陷阱）；预算对账偏差（used vs runs 正常收工数）从仅 WARN 升级为自动校正（以 runs 实际收工数为准重写 used，校正留痕）。

## Capabilities

### New Capabilities

- `archive-auto-commit`: spec_done push 流程尾部将归档移动自动 commit + push，保证归档产物随代码同仓同步。
- `cli-retry-backoff`: 同 spec 连续秒级失败触发的退避冷却与告警机制，阻断重试风暴。
- `per-agent-timeout-override`: run_timeout_seconds 的 agent_type 级覆盖映射，supervision 派生值联动；监督器内部 judge 超时配置化。
- `lifecycle-hygiene`: frozen 对 verifier 内部链生效、STATE 路径唯一化、预算对账自动校正三项卫生修复。

### Modified Capabilities

<!-- 无：spec/specs/ 当前无活跃能力；归档中 fix-push-ref-lifecycle 的 push 语义不变，本变更仅在其尾部追加归档提交动作。 -->

## Impact

- `core/pm_engine/dispatch.py` / `engine.py`：push 流程尾部追加归档提交；秒挂冷却判定挂入派发前闸门。
- `core/agent_runner/runner.py`：attempt 失败分类（秒挂识别）与冷却计数。
- `core/config.py`：`timeout_overrides` 解析、派生值联动（stuck 阈值 / supervision extension / absolute_max）、非法覆盖值护栏（低于下限打 ERROR 并回退全局值）。
- `core/agent_runner/liveness.py`：JUDGE_TIMEOUT_SECONDS 改读配置。
- `core/verify_engine/`（verifier 内部链）与 `core/pm_engine/reporting.py`：frozen 检查点。
- `core/pm_engine/budget.py` 或对账所在模块：自动校正逻辑。
- 运行时文件：删除 `.fenix/STATE.md`（空文件）；`.fenix/config.yaml` 新增可选键 `agents.timeout_overrides`（缺省零行为变化）。
