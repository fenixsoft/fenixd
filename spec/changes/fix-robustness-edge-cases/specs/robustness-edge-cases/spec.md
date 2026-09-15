# robustness-edge-cases

## ADDED Requirements

### Requirement: run 流归属必须全等匹配

所有按 spec 名查找 run 流文件的判定点 MUST 使用完整 spec 名全等比较，MUST NOT 仅凭 `glob(f"{prefix}-{spec_name}-*.jsonl")` 命中即认定归属。实现 MUST 复用既有的单一来源解析器（`run_spec_part`），对每个 glob 候选解析出完整 spec 名后再比较。

该解析器 MUST 能正确解析全部既有 run 产物命名形态，包括 attempt 后缀（`-a<n>`）与瞬态重试后缀（`-r<n>`）。若解析器对某形态返回非 spec 名，则该 spec 的在跑 run 会被全等守卫**漏掉**（假阴性），其危害等价于误命中：活性判定取假会误报 stuck 并触发误杀，预算豁免失效，任务进度与 planner 耗时取到旧产物。

#### Scenario: 前缀命中的他 spec 流被排除

- **WHEN** 存在 `impl-fix-x-y-<ts>.jsonl`，查询 spec `fix-x`
- **THEN** 该文件 MUST NOT 被计为 `fix-x` 的 run 流

#### Scenario: 全等匹配保留

- **WHEN** 存在 `impl-fix-x-<ts>.jsonl` 与 `impl-fix-x-y-<ts>.jsonl`，查询 spec `fix-x`
- **THEN** 只命中前者；查询 spec `fix-x-y` 只命中后者

#### Scenario: 后缀形态不得漏命中

- **WHEN** 存在 `impl-fix-x-<ts>-a1.jsonl` 或 `impl-fix-x-<ts>-a1-r2.jsonl`（attempt + 瞬态重试后缀），查询 spec `fix-x`
- **THEN** 两者 MUST 均被归属为 `fix-x`（全等守卫 MUST NOT 把它们排除）

#### Scenario: 判定点全覆盖

- **WHEN** 检查 worktree 残留判定（`core/worktree_manager.py:1265`）、活性判定（`core/agent_runner/liveness.py:284`）、recent-run-activity 判定（`core/pm_engine/engine.py:1986`）、预算豁免判定（`core/pm_engine/budget.py:336,355`）、任务进度（`core/run_task_track.py:74`）、planner 耗时（`core/pm_engine/verification.py:4174`）七处
- **THEN** 七处均使用全等匹配（任一遗漏即为不合规）；对形态更宽的同类点（`core/dashboard/data.py:1038` 的子串 glob）MUST 给出显式处置结论（纳入或书面 defer 并注明承接方）

### Requirement: 告警存储读损坏不得静默清空历史

`AdminStore` 在读取告警文件遇到解析失败时，MUST 先把损坏文件改名留底（形如 `.corrupt-<时间戳>`），再返回空集合；且在任何「读-改-写」回写前 MUST 校验记录数下限——当本次写入会导致既有历史整体丢失时 MUST 拒绝写回并记录告警。

#### Scenario: 损坏文件留底

- **WHEN** 告警文件内容为非法 JSON，发生一次读取
- **THEN** 原文件被改名保留为 `.corrupt-<ts>`，读取返回空集合，且产生一条可观测记录

#### Scenario: 拒绝清库式写回

- **WHEN** 一次写入会使既有历史记录整体消失
- **THEN** 写回被拒绝，历史文件不被覆盖

#### Scenario: 正常追加不受影响

- **WHEN** 告警文件合法且新增一条告警
- **THEN** 新记录追加，既有记录保留

#### Scenario: 损坏留底后仍可恢复写入

- **WHEN** 告警文件因损坏已被留底（`.corrupt-<ts>`），随后新增一条告警
- **THEN** 新告警 MUST 正常写入新文件，MUST NOT 因下限保护被拒绝（留底已保留历史取证，恢复写入不得被拦）

#### Scenario: 合法空集合不被误拦

- **WHEN** 告警文件不存在或内容为合法空数组，新增一条告警
- **THEN** 写入正常完成，MUST NOT 被下限保护拦截

### Requirement: 结构化日志不得有旁路写丢

除 `fenixd` 层级（可传播到已挂载的 handler）或显式注入的 Logger 实例外，代码 MUST NOT 使用裸 `logging.getLogger(...)` 记录运行时告警/错误。所有运行时 WARNING/ERROR MUST 落入结构化日志文件。

#### Scenario: 既有旁路模块被收敛

- **WHEN** 检查 `verify_scenarios`（`core/verify_scenarios.py:183,263`）、`spec_integrity`（`core/pm_engine/spec_integrity.py:61`）、`dashboard/server`（`core/dashboard/server.py:77`）、`scenario_static_check`（`core/verify_engine/scenario_static_check.py:29`）、`dashboard/registry`（`core/dashboard/registry.py:29,31`）、`screenshot_lab`（`core/verify_engine/screenshot_lab.py:31`）、`fast_track_result`（`core/fast_track_result.py:141`）中记录 WARNING/ERROR 的调用
- **THEN** 均通过可传播层级或注入 Logger，MUST NOT 为裸 `getLogger`（静态检查 MUST 覆盖全部裸 `getLogger` 点，不得只按白名单文件名枚举）

#### Scenario: 告警实际落盘

- **WHEN** 触发「持久化集加载净化剔除」这类告警
- **THEN** 该消息出现在结构化日志文件（`fenixd.log`）中

#### Scenario: 防回归检查在场

- **WHEN** 运行针对日志门面的静态检查或测试
- **THEN** 新引入的裸 `getLogger(...)` 会被检出
