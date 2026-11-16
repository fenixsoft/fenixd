## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: tests/test_push_git_env_precheck.py
  kind: new
```

## 1. 推送 git 环境预检

- [ ] 1.1 core/pm_engine/engine.py：_git_push_ref 前置 git 环境预检（remote 存在性 + 目标分支存在性），返回结构化结果 ok/no-remote/no-ref
- [ ] 1.2 core/pm_engine/engine.py：approve_push 与归档收口两处裸推遇 no-remote/no-ref 时标记 push=N/A 留痕短路，不进退避重试、不写 error 字段

## 2. 续推通道补门

- [ ] 2.1 core/event_bus.py：_recover_done_push_retry 追加 gates.approve_mode=manual 门，manual 项目不自动补投推送
- [ ] 2.2 core/event_bus.py：预检判 no-remote 的 done spec 续推走 N/A 留痕出口，不推进重试计数、不产生新失败记录

## 3. 分支解析与配置分级

- [ ] 3.1 core/pm_engine/engine.py：推送目标分支改为配置优先、缺省按仓库当前分支探测，消除 main 硬编码（approve_push 与归档收口同覆盖）
- [ ] 3.2 core/pm_engine/engine.py：pm.push.retry_backoff_seconds 键缺失静默用默认退避，键存在但非法保留 WARNING，分级消除缺键告警噪音

## 4. 测试

- [ ] 4.1 tests/test_push_git_env_precheck.py：覆盖无 remote/无目标分支的 N/A 短路语义、manual 审批门拦截续推、非 main 分支解析、缺键静默与非法告警分级
