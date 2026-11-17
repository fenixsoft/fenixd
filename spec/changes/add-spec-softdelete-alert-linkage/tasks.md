## Deliverables

```yaml
- path: core/admin_store.py
  kind: modify
- path: core/dashboard/data/spec_archive.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: tests/test_spec_softdelete_alert_linkage.py
  kind: new
```

## 1. 联动关闭告警

- [x] 1.1 AdminStore 新增按 spec 名联动关闭未处理告警的方法：escalation+signal 双 kind、`spec` 字段精确匹配（空/`global` 经 `is_global_spec` 单源谓词跳过）、已 handled 条目逐位不动、排他锁内单次读改写、写 `handled=True/handled_at/handled_by="spec-softdeleted"/resolve_note`（目录迁移形态注记含归档目录名，目录缺失仅清状态形态如实注记无目录，形态见 spec.md Requirement 1）、返回关闭条数；零命中零写回（mtime 不变）
- [x] 1.2 `soft_delete_spec` 成功路径接入 1.1 联动（fail-open）：告警写回失败不使删除失败、不回滚目录迁移，返回对象如实携带 `alerts_closed` 计数与 `alert_link_error` 失败说明，无未捕获异常逸出；联动失败说明仅落 `alert_link_error` 独立字段，顶层 `error` 字段保持删除本体语义（成功路径为 None）不被联动失败占用（`_exec_abandon` 与删除端点均以顶层 `error` 判失败）

## 2. abandon 幂等化

- [x] 2.1 `_exec_abandon` 对 `soft_delete_spec` 返回 `found=False` 改为幂等成功：ok=True、动作步骤含「spec 已不存在（STATE 与归档清单均无记录），视为已丢弃」，不再产生 `spec not found` 失败；`found=True` 与 `running`/一般 error 分支行为不变

## 3. 验证

- [x] 3.1 新增 `tests/test_spec_softdelete_alert_linkage.py` 覆盖四组场景：软删除成功关闭双 kind 未处理告警（注记含归档目录）、已 handled 告警与 disposition 台账逐位不动、告警写回失败时删除本体仍成功且如实回报、`found=False` 幂等成功与存量 spec 丢弃行为不变
- [ ] 3.2 核对前端告警面板 handled_by 渲染对 `spec-softdeleted` 取值走通用兜底（无枚举硬编码拦截），并跑全量既有测试套件确认零回归
