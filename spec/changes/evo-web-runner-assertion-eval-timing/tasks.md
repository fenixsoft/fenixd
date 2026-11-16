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

- [ ] 1.1 core/verify_engine/web_runner.py：断言求值计划按类型分桶——交互桶取 WEB_ASSERTION_LAYERS 第 2 层四类（no_click_interception/no_overlap/in_viewport/z_index_order），按「目标元素可见的最后一个步骤完成点」视图切换感知求值（含 trial click），目标元素全程不可见回退既有后置时机；no_console_error 等流程级断言保持既有后置统一求值不变；分层判定读断言声明、场景文件零改动、交互断言早期失败不中断后续步骤且结果保持声明序
- [ ] 1.2 core/verify_engine/assertions.py：trial click 与 not visible 失败分支附求值时刻视图状态快照（当前可见视图、目标元素所在视图、可见性判定依据）入失败载荷

## 2. 测试

- [ ] 2.1 tests/test_web_runner_assertion_eval_timing.py：导航切视图场景交互断言不再误报 not visible；流程级断言仍后置求值且结果与既有语义一致；not visible 失败载荷含视图快照字段（当前视图/元素所在视图/判定依据）；目标元素全程不可见场景回退后置求值且失败载荷含视图快照（真实缺陷不掩盖）；交互断言早期失败不中断后续步骤、assertion_results 保持声明序；已锚 #connect-btn 类场景在新时机下求值结果不变