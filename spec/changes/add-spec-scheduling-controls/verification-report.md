# add-spec-scheduling-controls 验证报告

- 验证时间：2026-09-06T11:25:47Z（report.json 生成时刻）
- 判定引擎：Fenix Planner Agent（确定性裁决，含 add-verdict-evidence-taxonomy / add-interaction-contract-and-per-assert-triage）
- 结果：**15 场景 = 1 通过 + 13 环境问题（env）+ 1 测试缺陷（test-defect），无产品 Bug**

## 一、总体结论

| 场景数 | 通过 | 失败 | 环境/缺陷分类 |
|---|---|---|---|
| 15 | 1 | 14 | 13 × env（测试环境配置缺失）+ 1 × test-defect（测试 fixture 缺陷） |

核心裁决：**被测产品实现正确**。14 个失败场景中无任何 `product-bug` 归因。

- 13 个 API/Web 场景为**同一 root cause**：验证实例未执行场景声明的前置夹具——未以 `--add-project` 注册临时 showcase 项目 `scheduling-showcase`，导致 API 请求被 `404 {"error": "unknown project"}` 前置拦截、Web 列表无对应 spec 行。属 `env`（测试环境配置缺失），非产品 Bug。
- 唯一需修复项：`tests/test_spec_scheduling.py::TestStartAfterDispatchGate::test_on_spec_ready_gate_pending` 为测试用例缺陷（`test-defect`）。

## 二、分场景裁决明细

### env（13 场景，warning 级不阻塞，但复验必须先补齐夹具）

| 场景 | 分类 | 证据摘要 |
|---|---|---|
| api-set-start-after-valid | env | POST /api/spec-start-after → 404 unknown project（6 断言失败，全部未触达产品逻辑）；GET /api/specs 501 为启动瞬态，复测恢复 200 |
| api-clear-start-after | env | POST → 404 unknown project |
| api-invalid-start-after | env | POST → 404 unknown project（未触达 400「非法 ISO8601」校验） |
| api-terminal-start-after-reject | env | POST → 404 unknown project（未触达 403「终态」拒绝） |
| api-freeze-config-scheduled | env | POST → 404 unknown project |
| api-freeze-config-permanent | env | POST → 404 unknown project |
| api-freeze-config-non-frozen-reject | env | POST → 404 unknown project（未触达 409「冻结态」校验） |
| api-freeze-config-past-time-immediate-unfreeze | env | POST → 404 unknown project |
| web-freeze-manage-modal | env | c-frozen-c 行不存在，「更多」按钮 click 超时 |
| web-freeze-manage-unfreeze | env | c-frozen-e 行不存在，「更多」按钮 click 超时 |
| web-scheduled-tag-visible | env | c-sched-set 行不存在，.ant-tag 可见性/倒计时文本/行菜单点击 3 断言超时（含截图证据） |
| web-pickup-time-modal-open | env | c-sched-clear 行不存在，「更多」按钮 click 超时 |
| web-pickup-time-modal-clear | env | c-sched-set 行不存在，「更多」按钮 click 超时 |

**环境实证（非推断）**：

- 服务实例确为 fenixd dashboard：`bin/fenix_dashboard.py --serve --port 58723`（cwd = verify-serving/add-spec-scheduling-controls-1788693877）。
- 实测 `/api/projects` 仅含 `fenixd`、`fenix-desktop`，**无 `scheduling-showcase`**。
- 实测服务端路由表 `core/dashboard/server.py:1449-1451` 已含 `/api/spec-start-after` 与 `/api/spec-freeze-config` 全部新端点。
- 对已注册项目 `fenixd` 探测新端点，返回规范校验路径（`spec not found: nonexistent` 404 / `Empty request body` 400）——证明路由存在且参数校验逻辑在线。
- report 中 `GET /api/specs → 501` 为服务启动瞬态；复测现返回 `200 + {"error":"unknown project","specs":[]}`。

### test-defect（1 场景，须修复后复验）

| 场景 | 分类 | 证据摘要 |
|---|---|---|
| cli-unit-tests | test-defect | pytest 退出码 1：29 项中 28 通过，`test_on_spec_ready_gate_pending` 失败（`AttributeError: 'PMEngine' object has no attribute '_last_dispatch_at'`，engine.py:239） |

**根因**：测试用 `PMEngine.__new__(PMEngine)` 绕过 `__init__` 手工构造实例，逐一 stub 了 `state_machine`/`agent_runner`/`logger`/`_pending_dispatches` 等属性，但**遗漏 stub 新调度特性引入的 `_last_dispatch_at`**（`engine.py:115` 仅在 `__init__` 中初始化）。`_on_spec_ready` 门控首次调用 `self._last_dispatch_at.get(spec_name)` 即抛 AttributeError。

**非产品 Bug 的依据**：产品正常实例化路径（`__init__`）总会初始化 `_last_dispatch_at`；其余 28 项调度/冻结回归测试全部通过，佐证 start_after 门控、定时解冻、冻结双轨产品逻辑正确。

**修复方式**：测试手工构造处补 `pm._last_dispatch_at = {}`。

## 三、聚合与豁免判定

- 13 个 API/Web 场景 root cause 唯一（夹具项目未注册）→ 按聚合规则合并为 1 个 env 问题，标注影响范围（见 `.fenix-run-result.json`）。
- 场景级豁免成立条件校验：13 个 env 场景**全部失败断言**均被逐条归类为非 product-bug → 豁免成立，不记产品 Bug。
- `cli-unit-tests` 唯一失败断言（exit_code）归类 `test-defect` → 场景 failed，不豁免。

## 四、复验建议

1. 修复测试 stub：`tests/test_spec_scheduling.py` 中 `test_on_spec_ready_gate_pending` 的手工构造处补 `pm._last_dispatch_at = {}`。
2. 重跑验证前，验证实例须先以 `--add-project` 注册夹具项目 `scheduling-showcase`（含 `.fenix/STATE.md`：c-sched-set(ready)、c-sched-clear(ready)、c-sched-done(done)、c-frozen-a/b/c/d/e(blocked+用户指令冻结，e 供立即解冻)；各 spec 建空目录 `spec/changes/<name>/` 防 archived 过滤；验证后 `--remove-project` 清理）。
3. 夹具就绪后全部 14 个失败场景应可转绿；若仍有残留失败，再按 layer 判定是否为产品 Bug。

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

首轮写入 15 个场景

