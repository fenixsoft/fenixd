## Deliverables

```yaml
- path: core/pm_engine/__init__.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_pm_verification.py
  kind: modify
- path: tests/test_pm_dispatch.py
  kind: modify
```

## 1. task-gap 常量与快照写点

- [x] 1.1 `core/pm_engine/__init__.py` 定义模块级常量 `TASK_GAP_ERROR_PREFIX = "task-gap:"`（单点定义，engine/dispatch/tests 共用 import，杜绝字面量漂移），附一行注释说明语义（verified→done 门禁任务缺口结论的结构化标记，恢复巡检据此识别「待人工裁决」）
- [x] 1.2 `core/pm_engine/dispatch.py` implementer 成功收口点（`is_success` 分支、`_reconcile_impl_budget` 之前）新增原子快照：把已解析的结果 dict 原样写入 `.fenix/verify-progress/<spec>/impl-result.json`（tempfile + `os.replace`，手法对齐 `engine.py` 的 `_sync_task_progress`）；快照失败（OSError 等）仅 WARNING 日志不阻塞主流程；重派后新成功自然覆盖旧快照
- [x] 1.3 fast-track 车道若与标准车道共享同一 `is_success` 收口点则一并获得快照；若代码路径分离，仅标准车道落地并在快照代码处注释注明 fast-track 不需要的原因（verified→done 与成功处理同周期同步执行，无跨 spec 覆盖窗口）

## 2. 门禁证据源与 fail 方向

- [x] 2.1 `core/pm_engine/engine.py` `_task_completion_blocker` 证据读取改为快照优先：先读 `.fenix/verify-progress/<spec>/impl-result.json`（stamp=本 spec 才采信），缺失时回退现有共享文件路径（维持 `_read_implementer_result` 既有 worktree/root 行为不变，仅门禁内部改读序，避免影响 dispatch 语义）
- [x] 2.2 fail-closed 分支：快照与共享文件（stamp=本 spec）皆缺失时——`STATE.implementer_run` 非空且 tasks.md 存在未勾数字任务（`N.M` 格式）→ 拦截，error = `TASK_GAP_ERROR_PREFIX + "run 证据缺失（快照与共享文件均无），需人工确认"`；`implementer_run` 为空 → 放行（legacy/手工兼容）；tasks.md 缺失或无数字编号任务 → 直接放行（现状不变）
- [x] 2.3 task-gap error 生命周期：拦截时 error 以 `TASK_GAP_ERROR_PREFIX` 开头并带缺口 ids（`task-gap: 未完成任务：4.2、4.3、4.4`）；放行路径清除既有 `task-gap:` 前缀 error（人工补勾感知路径）；与 vblocker 合并语义维持现状（并存时合并 error，vblocker 在场仍走 D7 回 testing）

## 3. 恢复机制尊重门禁结论

- [x] 3.1 `core/pm_engine/engine.py` BLOCKER CHECK（`Auto-recovering stuck SPEC` 处）：卡 verified 且 error 带 `TASK_GAP_ERROR_PREFIX` 前缀的 spec 不执行 auto-recover（无状态突变），blocker 条目 reason 改述为「任务缺口待人工裁决：<error 去前缀摘要>」；无前缀的卡 verified spec 维持现有 auto-recover 行为
- [x] 3.2 `core/event_bus.py` verified re-trigger 分支保留现状（不加 task-gap 抑制），在分支注释注明设计依据：快照落地后重评是确定性的（有缺口幂等再拦、人工补勾后放行），re-trigger 是人工修复的感知心跳

## 4. 测试与验证

- [x] 4.1 事故回归测试（`tests/test_pm_verification.py`）：门禁首次拦截（error 落 task-gap）→ 模拟共享文件被其它 spec stamp 覆盖 → re-trigger 重评 → 仍拦截且维持 verified（对齐 2026-09-07 fix-mobile-breakpoint-hook-tables 事故时序）
- [x] 4.2 兼容矩阵测试（`tests/test_pm_verification.py`，对齐 design D4 六行）：快照存在全勾放行；快照存在有缺口拦截；快照缺失共享文件兜底（stamp=本 spec 时按共享文件评估）；两者皆缺失+implementer_run 在场 fail-closed 拦截；无 implementer_run 放行；tasks.md 无数字编号任务放行
- [x] 4.3 快照写点测试（`tests/test_pm_dispatch.py`）：成功即快照（含 spec/status 字段）；重派覆盖旧快照；快照写失败主流程继续（WARNING 不抛出）
- [x] 4.4 人工补勾闭环 + 恢复尊重测试（`tests/test_pm_verification.py` 或 `tests/test_pm_dispatch.py`）：task-gap 拦截生效期间人工补勾 → re-trigger 放行 → error 清除 → done 后 auto-approve 正常；BLOCKER CHECK 对 task-gap 前缀 spec 不 auto-recover 且 reason 为待人工裁决形态；event_bus re-trigger 不被 task-gap 抑制
- [x] 4.5 全量回归：`python3 -m pytest tests/ -q` 通过，重点确认既有 verified→done 门禁测试（`_task_completion_blocker` 相关桩）无回归
