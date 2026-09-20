## Context

Fenix 是通用开发框架，被管项目不一定是 Python 项目。项目页「测试回归」分面在 `add-project-detail-tabs` 已预留 key（`list.tsx` 中 `key: 'regression'`，`children: null`）。全量回归目前只有 implementer 在 run 内手跑 `bin/run_full_suite.py`（pytest 专用），无独立车道、无历史、无可观测视图。

本次采用与 `code-review`（`add-code-review-agent-and-quality-tab`）**完全同构**的成熟范式：声明式执行契约（`verify.yaml`）+ 文件信号触发 + daemon 主循环消费 + 后台 worker + 巡检周期检查点 + 快照落盘 + 只读 API + 分面展示。避免发明新范式。

## Goals / Non-Goals

**Goals**
- 跨语言：执行命令与结果格式由 `verify.yaml` 声明，框架只认 JUnit XML，不硬编码 pytest。
- 可观测：全绿给概览，异常给明细表；无配置给引导态。
- 可周期化：与每日自省/code-review 同形的开关与调度。
- 零迁移：旧 `verify.yaml` 无 `regression` 段照常工作。

**Non-Goals**
- 不做回归结果的历史多点留存（本次只留 `last-run.json` 单快照；多轮历史后续可扩展）。
- 不做增量测试选择（`bin/test_for.py` 是另一条线）。
- 不改造 implementer run 内的回归契约（那条仍走 run 内 pipeline）。

## Decisions

### D1：执行声明放 `verify.yaml` 的新 `regression` 段（而非 config.yaml）

**决策**：`regression` 段归 `verify.yaml`，与 prepare/serve/ready 同层。

**理由**：verify.yaml 的定位就是"项目如何被测"——prepare 是构建、serve 是起服务、ready 是就绪、regression 是跑测试，四者同一语义域。放 config.yaml 会割裂；且 verify.yaml 已有"缺失即 AI 起草"通道，regression 段可直接复用。

**代价**：`core/verify_contract.py` 的 `VerifyContract` dataclass 需扩字段、`load_verify_contract` 需扩解析；但这是加法，不影响既有字段。

### D2：结果格式统一 JUnit XML

**决策**：`format: junit`，框架只写一个 JUnit XML 解析器。

**理由**：JUnit XML 是跨语言事实标准（pytest `--junit-xml`、jest-junit、go-junit-report、maven-surefire 均可产出；`testcase@time` 天然承载耗时，正是"长耗时用例"所需）。避免为每种语言写解析器。

**代价**：要求项目命令能产出 JUnit XML——但这由 AI 起草兜底，且是各自框架的一行参数。

### D3：文件信号 + daemon 主循环消费（照搬 code-review）

**决策**：`POST /api/regression/run` 只写 `.fenix/regression_request.json`；`fenixd._check_regression_requests` 在主循环消费——不新增线程。

**理由**：与 `_check_code_review_requests` / 取消 / approve_push 同族；托管态守卫（stopped/unmanaged 拒绝）已有成熟判据。HTTP 线程绝不同步跑长回归。

### D4：周期调度挂 admin 巡检检查点（照搬 `_run_code_review_checkpoint`）

**决策**：`admin_monitor._run_regression_checkpoint`，挂在既有巡检循环；守卫链 = `admin.regression.enabled` → run_at 时点 → 同自然日防重（独立 `state.json`）→ 单飞 → 有 regression 段。

**理由**：与 code-review 检查点逐条同构，运维心智一致；独立防重文件避免与自省/code-review 的状态互相覆盖（这正是 code-review 当年踩过的坑——不能复用 self_review_state）。

### D5：结果快照单文件 `.fenix/regression/last-run.json`

**决策**：覆盖式单快照，gitignored。

**理由**：首版只需"最近一次结果"，分面读它即可。历史多轮留待后续（spec 已注明 Non-Goal）。

### D6：结果 JSON 结构

```json
{
  "status": "passed|failed|timeout|parse_error|never_run",
  "cmd": "...", "output": "...",
  "started_at": "<ISO8601 UTC>", "finished_at": "<ISO8601 UTC>",
  "duration_seconds": 200.0,
  "total": 5045, "passed": 5041, "failed": 2, "errors": 1, "skipped": 1,
  "long_test_threshold_seconds": 10,
  "failures": [{"name":"...","file":"...","line":42,"time":1.2,"kind":"failure|error","message":"..."}],
  "long_tests": [{"name":"...","file":"...","line":7,"time":12.5}],
  "reason": "<parse_error/timeout 时的原因>"
}
```

`long_tests` 独立于 failures（一个慢但通过的用例也在其中）。

## Risks / Trade-offs

- **[R1] JUnit XML 形态差异**：不同框架的 XML 层级/属性命名略有差异（`testsuite` 嵌套 vs 平铺、`testcase@classname` 语义不同）。→ 解析器按宽松策略：递归找所有 `testcase`，`time` 缺失记 0，`file` 从 `file`/`classname` 兜底，`failure`/`error`/`skipped` 子元素判定。
- **[R2] 回归命令副作用**：命令在项目根执行，可能污染工作区（如生成产物）。→ 复用 `bin/run_full_suite.py` 已有的主机级锁思路不适用（跨语言）；改为文档声明"命令应幂等、产物落 `.fenix/regression/`"，并在 spec 的 verify.yaml 注释里说明。
- **[R3] 起草质量**：AI 探测不出测试命令时写错命令。→ 起草产物必须经自证落地（既有的"三段自证"扩展为"跑一次 regression.cmd 确认能产出 XML"），失败则省略该段而非写错。
- **[R4] 阈值归属歧义**：长耗时阈值放 verify.yaml 还是 config.yaml？→ 决策放 `verify.yaml`（测什么、什么算慢，都是项目测试体系属性）；设置页卡片以只读说明其来源 + 提供 verify.yaml 编辑入口（既有端点）。

## Migration Plan

- `verify.yaml` 无 `regression` 段 → 契约 `regression=None` → 分面引导态、周期检查点跳过、触发端点 400。存量项目零迁移。
- `config.yaml` 无 `admin.regression` 段 → `enabled` 缺省 false → 零动作。存量项目零迁移。
- 框架需重启 daemon 使新检查点/消费器生效（运维步骤，写入 help 文档）。

## Open Questions

（无——执行入口、格式、阈值归属已在澄清阶段定案。）
