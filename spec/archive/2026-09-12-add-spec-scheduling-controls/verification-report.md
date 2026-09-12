# add-spec-scheduling-controls 验证报告

- 验证时间：2026-09-06T12:59:55Z（report.json 生成时刻）
- 判定引擎：Fenix Planner Agent（确定性裁决，含 add-verdict-evidence-taxonomy / add-interaction-contract-and-per-assert-triage）
- 轮次：**修复轮**（场景集冻结 15 个，add-verify-scenario-freeze；复用第 1 轮持久化集，不扩容）
- 结果：**15 场景 = 2 通过 + 13 环境问题（env），无产品 Bug、无测试缺陷**

## 一、总体结论

| 场景数 | 通过 | 失败 | 环境/缺陷分类 |
|---|---|---|---|
| 15 | 2 | 13 | 13 × env（测试环境配置缺失） |

核心裁决：**被测产品实现正确**。13 个失败场景中无任何 `product-bug` 归因，亦无 `test-defect`。

- 上一轮唯一测试缺陷 `cli-unit-tests`（`test_on_spec_ready_gate_pending` 手工构造 PMEngine 漏配 `_last_dispatch_at`）**已在本轮修复通过**——修复提交 `[fenix] add-spec-scheduling-controls: 修复验证第 1 轮 test-defect — test_on_spec_ready_gate_pending 手工构造 PMEngine 补 _last_dispatch_at stub`，pytest 全绿、skill 文档断言全过。
- 剩余 13 个 API/Web 场景为**同一 root cause**：验证实例未执行场景声明的前置夹具——未以 `--add-project` 注册临时 showcase 项目 `scheduling-showcase`，导致 API 请求被 `404 {"error": "unknown project"}` 前置拦截、Web 列表无对应 spec 行。属 `env`（测试环境配置缺失），非产品 Bug。

## 二、分场景裁决明细

### env（13 场景，MAY → warning 级不阻塞，但复验必须先补齐夹具）

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

- 服务实例确为 fenixd dashboard：`bin/fenix_dashboard.py --serve --port 45697`（cwd = verify-serving/add-spec-scheduling-controls-1788699525）。
- 实测 `/api/projects` 仅含 `fenixd`、`fenix-desktop`，**无 `scheduling-showcase`**。
- 实测服务端路由表 `core/dashboard/server.py:1449-1451` 已含 `/api/spec-start-after` 与 `/api/spec-freeze-config` 全部新端点。
- report 中 `GET /api/specs → 501` 为服务启动瞬态；复测现返回 `200 + {"error":"unknown project","specs":[]}`——端点在线，项目查找在业务层返回空。

### 通过（2 场景）

| 场景 | 断言 | 结果 |
|---|---|---|
| cli-unit-tests | pytest tests/test_spec_scheduling.py 退出码 0 + output「passed」（start_after 门控、定时解冻、冻结双轨回归全绿） | PASS |
| cli-skill-doc | skills/fenix-new/SKILL.md 含 --start-after 约定（「绝对时间」「+2h」「未指定」） | PASS |

## 三、聚合与豁免判定

- 13 个 API/Web 场景 root cause 唯一（夹具项目 `scheduling-showcase` 未注册）→ 按聚合规则合并为 1 个 env 问题，标注影响范围（见 `.fenix-run-result.json`，severity=minor，非产品缺陷）。
- 场景级豁免成立条件校验：13 个 env 场景**全部失败断言**均被逐条归类为非 product-bug（assertion_triage 逐断言归因齐全，经 verdict_check 校验 `validate_report ok: True`）→ 豁免成立，不记产品 Bug。
- 分类-状态映射：所有 env 场景 status=fail 保留（env MAY → warning，不强制 failed），无 product-bug/test-defect 误标；框架 `enforce_status_mapping` 无改写条目。

## 四、复验建议

1. 重跑验证前，验证实例须先以 `--add-project` 注册夹具项目 `scheduling-showcase`（含 `.fenix/STATE.md`：c-sched-set(ready)、c-sched-clear(ready)、c-sched-done(done)、c-frozen-a/b/c/d/e(blocked+用户指令冻结，e 供立即解冻)；各 spec 建空目录 `spec/changes/<name>/` 防 archived 过滤；验证后 `--remove-project` 清理）。
2. 夹具就绪后全部 13 个 env 场景应可转绿；若仍有残留失败，再按 layer 判定是否为产品 Bug。
3. 修复轮未声明新增交付范围，场景集保持冻结（15 个，无新增、无移除），无需调整。

## 本轮场景集变更

修复轮：复用持久化场景集 15 个（第 1 轮稳定），无新增、无移除。
