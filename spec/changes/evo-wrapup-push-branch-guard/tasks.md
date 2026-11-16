## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_wrapup_push_branch_guard.py
  kind: new
```

## 1. 推送目标与成功判定

- [ ] 1.1 core/pm_engine/engine.py：封装基分支解析（检出分支优先、复用 core/git_base_branch.py 探测兜底），收尾推送（约 :3446）与归档推送（约 :3628）目标改用基分支
- [ ] 1.2 core/pm_engine/engine.py：推送成功判定（约 :3333）升级为远端 tip 前进断言（复用约 :3290-3320 的 SHA 比对），up-to-date 空转不计成功并发单条告警；:3512 pushed 门数据源同改

## 2. 启动对账

- [ ] 2.1 core/pm_engine/engine.py：daemon 启动路径对本地基分支相对远端的领先提交数对账并输出（rev-list --count），供日志与聚合面消费

## 3. 测试

- [ ] 3.1 tests/test_wrapup_push_branch_guard.py：覆盖「master 检出项目推送目标为 master」「空转推送不标 pushed 且告警单条」「tip 前进正常收口」「启动对账输出领先数」四场景