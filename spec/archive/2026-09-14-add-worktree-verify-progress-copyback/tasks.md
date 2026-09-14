## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_verify_progress_copyback.py
  kind: new
```

## 1. 拷回实现

- [x] 1.1 在 `core/agent_runner/runner.py` 成功路径（:2114 既有「根 result → 共享文件」拷贝的同级 `if success:` 块内）新增 per-spec verify-progress 目录拷回：worktree `.fenix/verify-progress/<spec>/` 存在时，逐文件 `shutil.copy2` 拷回主树同路径——主树缺失或 worktree mtime 较新才拷贝（D2 mtime 守卫），子目录递归；目录不存在零动作（D4）
- [x] 1.2 拷贝循环包 try/except OSError：单文件失败记 WARNING（logger `agent_runner`，含 spec 名与源/目标路径）后继续，不抛出不阻塞收尾（D3 fail-open）

## 2. 单元测试

- [x] 2.1 新增 `tests/test_verify_progress_copyback.py`：worktree 独有产物（`.fenix-run-result.json`、`test_scenarios.json`、嵌套子目录）成功拷回主树且内容逐字节一致（spec.md Scenario「产物仅在 worktree 时拷回主树」）
- [x] 2.2 mtime 守卫用例：主树版本较新时不被 worktree 陈旧产物覆盖；主树独有文件（冻结场景集替身、`impl-result.json` 替身）在拷回后原样保留（Scenario「主树已有所需文件时行为」）
- [x] 2.3 fail-open 用例：目标目录不可写（OSError）时 run 成功终态不受影响、WARNING 落日志（Scenario「拷贝异常时 run 照常收工」）
- [x] 2.4 零动作用例：worktree 无产物目录时不创建主树目录、无日志（Scenario「worktree 无产物目录」）

## 3. 收尾验证

- [x] 3.1 全量测试通过：`pytest tests/test_verify_progress_copyback.py tests/test_agent_runner.py` 全绿，无存量回归
