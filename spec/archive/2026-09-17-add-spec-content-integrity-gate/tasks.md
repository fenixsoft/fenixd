## Deliverables

```yaml
- path: core/pm_engine/spec_integrity.py
  kind: new
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/alert_lifecycle.py
  kind: modify
- path: tests/test_spec_content_integrity.py
  kind: new
```

## 1. 判定函数

- [x] 1.1 新建 `core/pm_engine/spec_integrity.py`：实现 `spec_has_content(project_root, spec_name)` 纯函数——目录不存在返回 False；目录内存在 `proposal.md`/`design.md`/`tasks.md`/`specs/**/*.md` 任一返回 True；其余返回 False；读目录 IO 异常记 WARNING 返回 True

## 2. 闸门封装与派发接入

- [x] 2.1 在 `core/pm_engine/spec_integrity.py` 实现闸门方法 `check_spec_content_missing(spec_name)`：调用 `spec_has_content`；无内容且状态非 blocked 时 `update_spec(status=blocked, error=内容缺失)` + `_send_human_escalation_alert(signal_type="spec_content_missing", severity="major")`；返回 True 表示已拦（blocked 幂等）
- [x] 2.2 `core/pm_engine/engine.py` 加薄转发 `_check_spec_content_missing(spec_name)`（同 `_check_impl_budget_exhausted` 的 type 转发风格）
- [x] 2.3 `core/pm_engine/dispatch.py` 在 implementer 分支（预算闸门旁）加内容闸门：命中即回滚队列占用 + `continue`（镜像预算闸门的三行回滚块）
- [x] 2.4 `core/pm_engine/dispatch.py` 在 fast-track 分支做同样接入

## 3. 告警生命周期闭环

- [x] 3.1 `core/alert_lifecycle.py` 的 `_SIGNAL_CONDITIONS` 新增 `"spec_content_missing": CONDITION_SPEC_TERMINAL_OR_UNBLOCKED`

## 4. 测试与校验

- [x] 4.1 新建 `tests/test_spec_content_integrity.py`：`spec_has_content` 各形态单测（不存在/空目录/只有无关文件/有 tasks/有 proposal/只有 specs 子目录/读目录异常放行）
- [x] 4.2 闸门命中集成断言：无内容 spec 派发前 → blocked + 告警记录 + 不启动 run；有内容 spec → 正常派发；已 blocked → 幂等不重复告警
- [x] 4.3 运行 `python3 .fenix/bin/fenix_spec.py status` 确认全 artifact done，并跑 lint 预检与测试套件全绿