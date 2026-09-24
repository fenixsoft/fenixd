## Deliverables

```yaml
- path: core/dashboard/data/quality_gates.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: tests/test_quality_gates_progress.py
  kind: modify
- path: tests/test_quality_gates_soft_alert.py
  kind: new
```

## 1 读侧平铺形态容错（quality-gates-form-tolerance）

- [ ] 1.1 core/dashboard/data/quality_gates.py 新增 `_adopt_flat_form(file_data) -> dict` 纯函数并在 parse_quality_gates 接入——仅当 `gates` 键缺失或非 dict 时尝试：候选门集 = 顶层值为 dict 且 status ∈ GATE_STATUSES 的键；候选非空且无「值为 dict 但 status 枚举外或缺 status」的顶层键则采信（字符串型元数据键如 updated_at 忽略），否则不采信返回空 dict；下游（契约外 gate-id 忽略、_run_gate_status、full-suite 双源）与嵌套路径逐字节一致
- [ ] 1.2 tests/test_quality_gates_progress.py 扩展六个分支用例：嵌套形态零回归（含空 gates dict）、纯平铺采信（含字符串 updated_at）、平铺中契约外 gate-id 被忽略、平铺含枚举外 status 整体不采信、空顶层 dict 不采信、损坏文件维持 unknown 语义

## 2 pending/unknown 兜底归因文案（quality-gates-explainability）

- [ ] 2.1 core/dashboard/data/quality_gates.py 在 parse_quality_gates 返回前加单点后处理：status=pending 且 detail 为空 → 「该门未了结（run 在飞或自查结果未落盘）」；status=unknown 且 detail 为空 → 「门禁记录缺失或损坏」；已有非空 detail 原样保留；status 与 done 计数不变；文案常量与 GATE_DESCS 同区放置并注明契约来源
- [ ] 2.2 tests/test_quality_gates_progress.py 扩展用例：pending 空详情填充、unknown 空详情填充、failed/implementing/full-suite 终态豁免等既有归因零覆盖、done 口径不变

## 3 宽松对账告警接人工告警面（quality-gates-soft-gate-alerts）

- [ ] 3.1 core/agent_runner/result_gate.py 的 _check_quality_gates_soft 对四类违规（顶层缺 gates、JSON 无法解析、契约外 gate-id、status 枚举外）在保留既有 WARNING 的同时经 AdminStore.append_if_absent 写 admin_alerts：signal_type=quality-gates-form-drift、severity=info、entry 含 spec 名/文件相对路径/违规描述、不注册 choices（不可裁决桶）；写入整体 try/except fail-open 仅记日志；既有「MUST NOT 打回/零失败终态」路径逐字节不变；参照同文件 result_gate.py:1473 的 AdminStore 使用先例
- [ ] 3.2 新增 tests/test_quality_gates_soft_alert.py：四类违规各产生一条告警且字段齐全、append_if_absent 去重（同 spec 同类别未处理期间不重复）、写入异常 fail-open 不影响收尾、软边界零回归（对账后无任何失败终态信号）

## 4 验证

- [ ] 4.1 定向验证全绿：pytest tests/test_quality_gates_progress.py tests/test_quality_gates_soft_alert.py；并以注释形式在测试文件头部记录「本 SPEC 未触碰前端，src/ 下 qualityGates 相关模块零改动」的自查结论
