## Deliverables

```yaml
- path: core/verify_engine/web_runner.py
  kind: modify
- path: core/verify_engine/assertions.py
  kind: modify
- path: tests/test_web_runner_assertion_eval_timing.py
  kind: new
```

## 1. 断言求值时机分层

- [ ] 1.1 core/verify_engine/web_runner.py：断言求值计划按类型分桶——no_click_interception 等交互型断言绑定目标步骤索引并在该步骤完成点求值（含 trial click），no_console_error 等流程级断言保持既有后置统一求值不变；分层判定读断言声明、场景文件零改动
- [ ] 1.2 core/verify_engine/assertions.py：trial click 与 not visible 失败分支附求值时刻视图状态快照（当前可见视图、目标元素所在视图、可见性判定依据）入失败载荷

## 2. 测试

- [ ] 2.1 tests/test_web_runner_assertion_eval_timing.py：导航切视图场景交互断言不再误报 not visible；流程级断言仍后置求值且结果与既有语义一致；not visible 失败载荷含视图快照字段（当前视图/元素所在视图/判定依据）