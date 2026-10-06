## Deliverables

```yaml
- path: core/evolution.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: tests/test_evolution_product_salvage.py
  kind: modify
- path: tests/test_self_evolution.py
  kind: modify
```

## 1. 校验宽口径（输出侧对齐输入侧）

- [x] 1.1 core/evolution.py：read_contract（:2159-2222）对单条目契约错误（section 越界等）改为收集 per-item 错误并跳过该条、合法条目照常返回（返回形态附错误清单或新增 lenient 参数，默认行为对既有调用方兼容）；全部条目非法仍整体抛 ContractError。
- [x] 1.2 core/agent_runner/maintenance_runs.py：混合产物在宽口径 read_contract（1.1）下不再抛异常，落库侧走 ``contract is not None`` 常规分支、复用 :1109-1123 既有 partial 语义——有合法条目即落库合法条目、run_ok=False、水位不推进（下检查点幂等补齐）；:1048-1068 except ContractError 分支仅保留全非法与文件级错误；失败现场产物文件按 design D4 在 :1150-1159 finally 清理前改名 ``<原路径>.failed`` 留档，错误文案附留档路径。

## 2. 测试

- [x] 2.1 tests/test_evolution_product_salvage.py：补「单条非法小节→跳该条、其余登记落库、水位不推进」与「全部非法→仍整体拒绝」两形态用例；失败现场产物文件留档断言。
- [x] 2.2 tests/test_self_evolution.py：覆盖 read_contract 新返回形态——per-item 错误收集、合法条目通过、默认调用行为不变。