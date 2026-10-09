## Deliverables

```yaml
- path: core/v2_dev_server.py
  kind: modify
- path: core/agent_runner/v2_server.py
  kind: modify
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: tests/test_v2_devserver_fallback_attribution.py
  kind: new
```

## 1. 回退形态归因恢复

- [x] 1.1 core/v2_dev_server.py：start() 回退分支（:140-157）给 dev-server 进程 argv 附加 worktree 路径标记（标记 token 追加 argv 尾部——dev-server.mjs 位置参数 argv[2]/argv[3] 不可前插；形态取 `<wt>/core/dashboard/static` 对齐 _dev_server_worktree_root 的 static-root token 判据），使 _dev_server_worktree_root（:464-486）与既有豁免 _worktree_has_live_referencing_process（:489-510）可归因在服 run；修正 :142 附近「该形态罕见」注释（对非框架目标项目为常态形态）。
- [x] 1.2 core/worktree_manager/lifecycle.py：_provision_worktree_deps（:316，create 两出口 :187/:298 共用）为 worktree 补 core/dashboard/static 软链，消除回退形态本身；软链失败不阻塞 create、静默降级。

## 2. 清扫记账、扫描收窄与文案纠偏

- [x] 2.1 core/v2_dev_server.py：skip 分支（:533-549）与 cleanup_orphans（:571-590）按 pid 记账（进程内状态、重启即失不持久化）——首见告警一次、后续静默计数；升级/处置以「无引用进程」判定为前提，禁止按裸存活时长自动 kill；pgrep 扫描面按项目收窄（:384-397/:526），双 daemon 不互刷。
- [x] 2.2 core/v2_dev_server.py：skip 告警文案改为与归因/引用判定联动的条件文案（说明判定局限与误杀在服 run 风险），移除无条件「可手动 kill」建议；顺带修正 :534-538 skip 分支注释中「该形态罕见」表述（对非框架目标项目为常态形态）。
- [x] 2.3 core/agent_runner/v2_server.py：_v2_servers（:37-48）登记持久化或 daemon 启动按端口段+argv 对账，重启后仅收割无主回退形态进程（参照 core/serving_registry.py:351-394 的记账+身份核对+收割形态）。

## 3. 测试

- [x] 3.1 tests/test_v2_devserver_fallback_attribution.py（新建）：回退形态 argv 标记归因、在服 run 免于 skip 告警与收割、pid 记账首见一次后续静默、项目收窄后双 daemon 不互刷、重启对账只杀无主、告警文案断言（不含无条件手动 kill 建议）。
- [x] 3.2 运行既有 tests/test_v2_dev_server*.py 与 worktree lifecycle 相关用例，确认归因标记与软链改动零回退。
- [x] 3.3 tests 覆盖 1.2 软链 provisioning：worktree 缺 core/dashboard/static 时软链创建后 start() 不再回退主树静态根；软链失败静默降级（仅 WARNING）且 create 不阻塞派发。