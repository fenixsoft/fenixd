# Tasks: fix-scheduling-kick-single-slot

## Deliverables

```yaml
- path: core/signals.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/dashboard/data/__init__.py
  kind: modify
- path: core/dashboard/routes/spec_routes.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: bin/fenix_cli.py
  kind: modify
- path: tests/test_scheduling_kick_signal.py
  kind: new
- path: tests/test_dashboard_api.py
  kind: modify
- path: tests/test_spec_scheduling.py
  kind: modify
- path: tests/test_start_after_gate.py
  kind: modify
- path: docs/help/06-governance.md
  kind: modify
```

## 1. 信号载体层（core/signals.py）

- [x] 1.1 在 `core/signals.py` 新增常量 `SCHEDULING_KICK_DIR = ".fenix/scheduling_kick"`（目录形态，注释说明由单文件单槽位演进而来、旧常量 `SCHEDULING_KICK_REQUEST` 走向只读兼容）
- [x] 1.2 新增 SPEC 名合法性校验函数（供写入路径复用；校验失败返回明确错误描述）。判据 MUST 复用仓库既有的 kebab-case 权威校验（`core/spec_gen.py:_KEBAB_RE`，即 `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`）——黑名单式拒绝（仅查空串 / `/` / `\` / `..`）不足以覆盖 `.`、前导点、含 `:` 或非 ASCII 等「可作文件名但不合规」的输入
- [x] 1.3 新增 `write_scheduling_kick(project_root, spec) -> dict`：原子写（`tempfile.mkstemp` + `os.fsync` + `os.replace`）到 `<SCHEDULING_KICK_DIR>/<spec>.json`，内容 `{"spec", "action": "clear-start-after", "created"}`；返回 `{"ok": bool, "file": str|null, "error": str|null}`；任何异常 MUST NOT 向上抛出，一律转为 `ok: false` + 非空 `error`。**临时文件名 MUST NOT 以 `.json` 结尾**（如 `<spec>.json.tmp.<rand>`，且与目标文件同目录以保证 `os.replace` 原子性）——消费侧「只扫 `*.json`」的约束不得被并发写入中的临时文件命中

## 2. 写入侧与返回值契约（admin_actions.py）

- [x] 2.1 `core/dashboard/data/admin_actions.py` 的 `_write_scheduling_kick_signal` 改为委托 `core.signals.write_scheduling_kick`，保留同名函数与 `{"ok", "conflict", "file"}` 形状兼容（`conflict` 恒为 `False`——多槽位下不再存在跨 SPEC 冲突）
- [x] 2.2 `set_spec_start_after` 清空分支改为捕获写入结果并在返回值中新增 `scheduling_kick: {"ok": bool, "error": str|null}`；`normalized is None` 之外的路径该字段为 `null`
- [x] 2.3 `activate_spec` 同样在返回值中新增 `scheduling_kick` 字段
- [x] 2.4 `core/dashboard/data/__init__.py` 门面 re-export 新增/更名的符号（`SCHEDULING_KICK_DIR`、`write_scheduling_kick`），保持既有 `SCHEDULING_KICK_REQUEST` re-export 不破——`tests/test_dashboard_data_modules_contract.py` 以 `MODULE_CONSTANTS` 清单核对门面可达性，`SCHEDULING_KICK_REQUEST` 仍在该清单内，MUST NOT 直接删除该常量
- [x] 2.5 `bin/fenix_cli.py` 的 `cmd_activate`：按 `result["scheduling_kick"]` 分支输出——信号写出成功时维持现有「已激活，立即进入调度」文案；失败时 MUST NOT 再宣称「立即进入调度」，改为输出即时唤醒未生效、将由后续扫描派发的说明（退出码仍为 0——`start_after` 已成功置 null）。CLI 是与 Dashboard 并列的用户入口，受 `spec-manual-activation`「动作方 MUST 如实回报」约束

## 3. API 透传（spec_routes.py）

- [x] 3.1 `_api_spec_start_after` 读取 `result["scheduling_kick"]`：`ok` 为真则响应不含 `warning`；为假则响应携带 `warning`（非空，说明「即时唤醒信号写入失败，将由下次扫描（缺省 ≤30 分钟，即 `schedule.poll_interval_minutes`）派发」），且响应 `ok` 仍为 `true`
- [x] 3.2 `_api_spec_activate` 同款透传（成功响应体新增 `warning` 字段，仅在信号失败时出现）

## 4. 消费侧（fenixd.py）

- [x] 4.1 `_check_scheduling_kick_requests` 改为扫描 `<PROJECT_ROOT>/<SCHEDULING_KICK_DIR>` 目录下的 `*.json` 条目（目录不存在视为空；非 `.json` 条目一律忽略且 MUST NOT 删除——避免误删并发写入中的临时文件），逐条「读取 → 按 spec 当前状态唤起（drafted 走 `_on_spec_drafted`，否则 `_on_spec_ready`）→ 唤起成功后删除 → `_process_queue`」。**先唤起后删**（与旧单文件路径「先读后删」的家族写法不同）：唤起抛异常时信号保留留待下轮重试（对齐 `scheduling-kick-signal` 能力的「异常者留待下轮重试」场景），删除失败亦留待下轮；重复唤起由下游 handler 既有幂等谓词吸收
- [x] 4.2 逐条消费相互隔离：单条信号处理异常捕获记日志后继续下一条，MUST NOT 中断同轮其余信号；删除失败留待下轮
- [x] 4.3 损坏/非法 JSON/缺 `spec` 字段的信号文件删除防卡死；`spec` 已不在 STATE.md 时删除信号并记日志
- [x] 4.4 旧的单文件路径 `.fenix/scheduling_kick_request.json` 兼容消费：存在时按既有语义消费并删除（只读兼容，新写入不再产生该路径），并让旧路径处理与目录扫描在同一轮内互不阻塞；旧文件同样适用 4.5 的回收阈值分档——`created` 早于阈值的旧文件仅删除、MUST NOT 唤起（与目录条目同判据，防 daemon 长期停机期间残留的旧信号在恢复时引发一轮病态集中派发；现场 `/root/activation-showcase/.fenix/scheduling_kick_request.json` 写于 09-18 且至今未消费，正属此类）
- [x] 4.5 新增 `_reclaim_stale_scheduling_kicks`：对目录条目按 `created` 分档——阈值（代码常量 1 小时）内先消费再删（幂等），超阈值仅删不唤起；`created` 缺失/非法按陈旧处理（仅删）；目录内非 `*.json` 的残留（写入中断留下的临时文件）亦按同一阈值清理，但 MUST NOT 在 4.1 的消费扫描中被当作损坏信号删除
- [x] 4.6 把 `_reclaim_stale_scheduling_kicks` 挂到启动清扫与周期计时段（复用既有 600s 孤儿清扫时点），异常捕获记日志不中断主循环。**启动侧调用点 MUST 位于 `self.event_bus.start()`（同步建立 STATE 基线快照）之后、进入主循环之前**——早于基线快照的唤起会写 STATE，使该 SPEC 被后续 `_dispatch_changes` 当作新变化重放（对齐 `fenixd.py` 中 2026-09-07 hook 全量重放事故的注释约定）

## 5. 前端文案分支

- [x] 5.1 `core/dashboard/static/src/services/dashboard.ts`：`StartAfterResult` 与 `ActivateResult` 类型新增可选 `warning?: string`
- [x] 5.2 `core/dashboard/static/src/pages/projects/list.tsx`：清空定时成功后按 `warning` 分支文案——无则「已清除定时，立即恢复调度」，有则提示即时唤醒未生效、将由后续扫描派发
- [x] 5.3 `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`：激活动作同款文案分支
- [x] 5.4 在 `core/dashboard/static/` 下执行 `npm run build` 重建主树产物 `core/dashboard/static/dist/index.html`（构建产物不入库，声明为 reference；本任务只保证构建可过）

## 6. 测试

- [x] 6.1 新增 `tests/test_scheduling_kick_signal.py`：覆盖写入助手（成功落盘路径与内容 / 非法 spec 名拒绝且不越目录 / 原子性：并发或中断下不产生半写文件）与返回值契约（失败时 `ok:false` + 非空 `error`，异常不外抛）
- [x] 6.2 `tests/test_dashboard_api.py` 新增用例：连续清空两个 SPEC 的 `start_after` → 两次响应均 `ok:true`，`.fenix/scheduling_kick/` 下两个文件同时存在（锁死本次事故形态）；信号写入失败（monkeypatch 助手抛错或目录不可写）→ 响应带非空 `warning` 且 `start_after` 已为 null
- [x] 6.3 `tests/test_dashboard_api.py` 新增用例：连续激活两个 `manual` SPEC → 两个信号文件并存，无 409/丢弃
- [x] 6.4 `tests/test_spec_scheduling.py` 更新消费侧用例：目录多信号同轮消费、单条异常不影响其余、损坏文件被清理、旧单文件路径仍被消费并删除
- [x] 6.5 `tests/test_spec_scheduling.py` 新增陈旧回收用例：`created` 超阈值的条目仅删不唤起；阈值内的条目先唤起后删除；`created` 缺失条目仅删
- [x] 6.6 `tests/test_start_after_gate.py` 同步路径断言（原断言 `scheduling_kick_request.json` 的用例改为新目录形态，并保留一条旧路径兼容断言）
- [x] 6.7 新增用例：陈旧回收对**旧单文件路径**同样生效（`created` 超阈值 → 仅删不唤起；阈值内 → 先消费后删除），锁死 4.4/4.5 的分档语义
- [x] 6.8 新增用例：目录中存在非 `.json` 残留（模拟写入中断的临时文件）时，消费扫描不得删除它、且不被当作损坏信号；陈旧回收终将其清走
- [x] 6.9 新增用例：信号写出失败时 `cmd_activate`（CLI）不输出「立即进入调度」且 exit 0——锁死 2.5 的诚实回报契约

## 7. 文档

- [x] 7.1 `docs/help/06-governance.md` 的定时拾取小节更新：信号载体改为每 SPEC 一文件、写出失败时的诚实回报语义、陈旧信号 1 小时回收阈值（代码常量，不可配置）、旧单文件路径的兼容说明

## 8. 收尾

- [x] 8.1 运行 `python3 bin/run_full_suite.py --timeout 3600` 全量回归并修复本次改动引入的失败
- [x] 8.2 执行收尾代码质量审查（`bin/ocr_review.py`）并按处置契约把结果写入 `.fenix/verify-progress/fix-scheduling-kick-single-slot/code-review.json` 与 `.fenix-run-result.json` 的 `code_review.dispositions`

## 人工步骤（不写成任务，供人工在主树执行）

- 存量项目主树若残留 `.fenix/scheduling_kick_request.json`，无需人工清理——消费侧兼容路径会在 daemon 下一轮消费时删除它。
- 本仓库 `docs/help/06-governance.md` 中 `/fenix-ready` 相关描述由仓库内文档承载；仓库外的 `~/.claude/skills/fenix-ready/` 若有联动文案需人工同步（非本仓库交付物）。
