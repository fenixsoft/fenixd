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

- [ ] 1.1 在 `core/signals.py` 新增常量 `SCHEDULING_KICK_DIR = ".fenix/scheduling_kick"`（目录形态，注释说明由单文件单槽位演进而来、旧常量 `SCHEDULING_KICK_REQUEST` 走向只读兼容）
- [ ] 1.2 新增 SPEC 名合法性校验函数（拒绝空串、含 `/`、含 `\`、含 `..`），供写入路径复用；校验失败返回明确错误描述
- [ ] 1.3 新增 `write_scheduling_kick(project_root, spec) -> dict`：原子写（`tempfile.mkstemp` + `os.fsync` + `os.replace`）到 `<SCHEDULING_KICK_DIR>/<spec>.json`，内容 `{"spec", "action": "clear-start-after", "created"}`；返回 `{"ok": bool, "file": str|null, "error": str|null}`；任何异常 MUST NOT 向上抛出，一律转为 `ok: false` + 非空 `error`

## 2. 写入侧与返回值契约（admin_actions.py）

- [ ] 2.1 `core/dashboard/data/admin_actions.py` 的 `_write_scheduling_kick_signal` 改为委托 `core.signals.write_scheduling_kick`，保留同名函数与 `{"ok", "conflict", "file"}` 形状兼容（`conflict` 恒为 `False`——多槽位下不再存在跨 SPEC 冲突）
- [ ] 2.2 `set_spec_start_after` 清空分支改为捕获写入结果并在返回值中新增 `scheduling_kick: {"ok": bool, "error": str|null}`；`normalized is None` 之外的路径该字段为 `null`
- [ ] 2.3 `activate_spec` 同样在返回值中新增 `scheduling_kick` 字段
- [ ] 2.4 `core/dashboard/data/__init__.py` 门面 re-export 新增/更名的符号（`SCHEDULING_KICK_DIR`、`write_scheduling_kick`），保持既有 `SCHEDULING_KICK_REQUEST` re-export 不破

## 3. API 透传（spec_routes.py）

- [ ] 3.1 `_api_spec_start_after` 读取 `result["scheduling_kick"]`：`ok` 为真则响应不含 `warning`；为假则响应携带 `warning`（非空，说明「即时唤醒信号写入失败，将由下次扫描（≤30 分钟）派发」），且响应 `ok` 仍为 `true`
- [ ] 3.2 `_api_spec_activate` 同款透传（成功响应体新增 `warning` 字段，仅在信号失败时出现）

## 4. 消费侧（fenixd.py）

- [ ] 4.1 `_check_scheduling_kick_requests` 改为扫描 `<PROJECT_ROOT>/<SCHEDULING_KICK_DIR>` 目录，逐条「读取 → 删除 → 按 spec 当前状态唤起（drafted 走 `_on_spec_drafted`，否则 `_on_spec_ready`）→ 唤起后 `_process_queue`」
- [ ] 4.2 逐条消费相互隔离：单条信号处理异常捕获记日志后继续下一条，MUST NOT 中断同轮其余信号；删除失败留待下轮
- [ ] 4.3 损坏/非法 JSON/缺 `spec` 字段的信号文件删除防卡死；`spec` 已不在 STATE.md 时删除信号并记日志
- [ ] 4.4 旧的单文件路径 `.fenix/scheduling_kick_request.json` 兼容消费：存在时按既有语义消费并删除（只读兼容，新写入不再产生该路径），并让旧路径处理与目录扫描在同一轮内互不阻塞
- [ ] 4.5 新增 `_reclaim_stale_scheduling_kicks`：对目录条目按 `created` 分档——阈值（代码常量 1 小时）内先消费再删（幂等），超阈值仅删不唤起；`created` 缺失/非法按陈旧处理（仅删）
- [ ] 4.6 把 `_reclaim_stale_scheduling_kicks` 挂到启动清扫（`fenixd.start()` 就绪后）与周期计时段（复用既有 600s 孤儿清扫时点），异常捕获记日志不中断主循环

## 5. 前端文案分支

- [ ] 5.1 `core/dashboard/static/src/services/dashboard.ts`：`StartAfterResult` 与 `ActivateResult` 类型新增可选 `warning?: string`
- [ ] 5.2 `core/dashboard/static/src/pages/projects/list.tsx`：清空定时成功后按 `warning` 分支文案——无则「已清除定时，立即恢复调度」，有则提示即时唤醒未生效、将由后续扫描派发
- [ ] 5.3 `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`：激活动作同款文案分支
- [ ] 5.4 在 `core/dashboard/static/` 下执行 `npm run build` 重建主树产物 `core/dashboard/static/dist/index.html`（构建产物不入库，声明为 reference；本任务只保证构建可过）

## 6. 测试

- [ ] 6.1 新增 `tests/test_scheduling_kick_signal.py`：覆盖写入助手（成功落盘路径与内容 / 非法 spec 名拒绝且不越目录 / 原子性：并发或中断下不产生半写文件）与返回值契约（失败时 `ok:false` + 非空 `error`，异常不外抛）
- [ ] 6.2 `tests/test_dashboard_api.py` 新增用例：连续清空两个 SPEC 的 `start_after` → 两次响应均 `ok:true`，`.fenix/scheduling_kick/` 下两个文件同时存在（锁死本次事故形态）；信号写入失败（monkeypatch 助手抛错或目录不可写）→ 响应带非空 `warning` 且 `start_after` 已为 null
- [ ] 6.3 `tests/test_dashboard_api.py` 新增用例：连续激活两个 `manual` SPEC → 两个信号文件并存，无 409/丢弃
- [ ] 6.4 `tests/test_spec_scheduling.py` 更新消费侧用例：目录多信号同轮消费、单条异常不影响其余、损坏文件被清理、旧单文件路径仍被消费并删除
- [ ] 6.5 `tests/test_spec_scheduling.py` 新增陈旧回收用例：`created` 超阈值的条目仅删不唤起；阈值内的条目先唤起后删除；`created` 缺失条目仅删
- [ ] 6.6 `tests/test_start_after_gate.py` 同步路径断言（原断言 `scheduling_kick_request.json` 的用例改为新目录形态，并保留一条旧路径兼容断言）

## 7. 文档

- [ ] 7.1 `docs/help/06-governance.md` 的定时拾取小节更新：信号载体改为每 SPEC 一文件、写出失败时的诚实回报语义、陈旧信号 1 小时回收阈值（代码常量，不可配置）、旧单文件路径的兼容说明

## 8. 收尾

- [ ] 8.1 运行 `python3 bin/run_full_suite.py --timeout 3600` 全量回归并修复本次改动引入的失败
- [ ] 8.2 执行收尾代码质量审查（`bin/ocr_review.py`）并按处置契约把结果写入 `.fenix/verify-progress/fix-scheduling-kick-single-slot/code-review.json` 与 `.fenix-run-result.json` 的 `code_review.dispositions`

## 人工步骤（不写成任务，供人工在主树执行）

- 存量项目主树若残留 `.fenix/scheduling_kick_request.json`，无需人工清理——消费侧兼容路径会在 daemon 下一轮消费时删除它。
- 本仓库 `docs/help/06-governance.md` 中 `/fenix-ready` 相关描述由仓库内文档承载；仓库外的 `~/.claude/skills/fenix-ready/` 若有联动文案需人工同步（非本仓库交付物）。
