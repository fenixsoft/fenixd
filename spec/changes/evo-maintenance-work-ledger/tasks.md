## Deliverables

```yaml
- path: core/maintenance_ledger.py
  kind: new
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_maintenance_ledger.py
  kind: new
- path: tests/test_admin.py
  kind: modify
```

## 1. 维护登记台账

- [ ] 1.1 core/maintenance_ledger.py（新建）：append_maintenance_entry(project, scope, actor, evidence, note, run_id=None) 按行追加 JSON 到项目 .fenix/maintenance_log.jsonl（字段 ts/scope/actor/evidence/note/run_id），文件不存在则创建、写入用追加模式；list_maintenance_entries(project) 读取全量条目并对坏行容错跳过
- [ ] 1.2 core/maintenance_ledger.py：登记条目的 run_id 字段与 maintenance- 前缀 run 关联的读写辅助，供告警归因与盘点引用

## 2. 前缀识别同步

- [ ] 2.1 core/agent_runner/run_files.py：RUN_ID_AGENT_PREFIXES（:32 起，定义处注释自述唯一真源）新增 maintenance- 前缀及类型映射
- [ ] 2.2 core/admin_monitor.py：_RUN_PREFIXES（:570 起）同步 maintenance-，使登记型 run 在告警归因/盘点视图中识别为有名主体而非泛型无主 agent

## 3. 测试

- [ ] 3.1 tests/test_maintenance_ledger.py（新建）：覆盖追加/读取/空文件自动创建/坏行容错/run_id 关联字段读写
- [ ] 3.2 tests/test_admin.py：覆盖 maintenance- 前缀在 RUN_ID_AGENT_PREFIXES 与 _RUN_PREFIXES 两处的类型识别
