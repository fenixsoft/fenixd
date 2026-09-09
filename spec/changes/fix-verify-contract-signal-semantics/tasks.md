## Deliverables

```yaml
- path: core/dashboard/server.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/ProjectProfilePanel.tsx
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
- path: tests/test_verify_contract_autodraft.py
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 端点信号语义拆分（verify-contract-signal-dispatch）

- [ ] 1.1 `core/dashboard/server.py` `_api_verify_yaml_autodraft_post`：派发分支二分——契约缺失/解析失败（contract is None）→ 照旧写 `verify_contract_missing`；契约可解析且 overwrite=true → 改写 `verify_contract_redraft`（severity=major、source=ui-manual、overwrite 标记、evidence 项目名格式「项目名=<name>; 覆盖确认=是」不变）；skipped 路径（可解析且无 overwrite）不动
- [ ] 1.2 `core/admin_monitor.py` 注册 redraft：SIGNAL_SEVERITY 加 `"verify_contract_redraft": "major"`；SIGNAL_RECOMMENDATION 加 redraft 专用指引（先复核现有契约有效性，有效契约按 D4 边界默认不碰、用户已显式授权覆盖时方可重起草，重起草草稿仍须经 bin/fenix_verify_contract.py 三段自证全通才落位）；STORED_SIGNAL_TYPES 追加该类型
- [ ] 1.3 `core/admin_monitor.py` `_detect_family_explosion`：spec 空值时的 evidence 项目名提取条件由 `stype == "verify_contract_missing"` 扩为 `stype in ("verify_contract_missing", "verify_contract_redraft")`

## 2. 服务端在途去重（autodraft-dispatch-dedup）

- [ ] 2.1 `_api_verify_yaml_autodraft_post` 写信号前查重：`AdminStore.read_all()` 过滤 kind=SIGNAL、signal_type 与本次待写类型相同、handled=false、evidence 含「项目名=<name>」；命中则不写新记录，响应仍 dispatched 且 message 注明已有在途请求；missing 与 redraft 异类型互不抑制

## 3. 前端防重入锁（autodraft-dispatch-dedup）

- [ ] 3.1 `ProjectProfilePanel.tsx`：新增 `autodraftInFlight = useRef(false)`；`handleAutodraft` 入口同步检查并置位（true 时直接 return），finally 复位；与既有 `setAutodraftLoading` 并存，锁语义以 ref 为准

## 4. 测试

- [ ] 4.1 `tests/test_dashboard_api.py`：既有 `test_autodraft_valid_contract_with_overwrite_dispatches` 断言更新为写入 `verify_contract_redraft`；新增在途去重测试（同类型未消费信号存在时二次触发不落盘 + 已 handled 信号不抑制 + missing 在途不抑制 redraft）
- [ ] 4.2 `tests/test_verify_contract_autodraft.py`：新增 redraft 消费测试——未 escalated 的 redraft 信号被 admin_monitor 拾取、按 evidence 提取项目名、SIGNAL_RECOMMENDATION 含复核/显式授权语义且与 missing 指引可区分
