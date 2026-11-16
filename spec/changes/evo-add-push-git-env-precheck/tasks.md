## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: tests/test_push_git_env_precheck.py
  kind: new
- path: tests/test_spec_approve_push.py
  kind: modify
```

## 1. 推送 git 环境预检

- [x] 1.1 core/pm_engine/engine.py：_git_push_ref 前置 git 环境预检（remote 存在性 + 目标分支存在性）；返回契约保持 (bool, str) 二元组不变，no-remote/no-ref 以 error 文本 "[push_na:no-remote|no-ref] <原因>" 结构化标记表达（既有打桩与解包零改动）
- [x] 1.2 core/pm_engine/engine.py：approve_push 与归档收口两处裸推遇 [push_na:* 标记时写 push=N/A 持久留痕（entry 专用字段，不走 error 字段）短路，不进退避重试；第三调用方 _push_branch_best_effort 遇标记按既有 best-effort 口径降级为 info 级跳过

## 2. 续推通道补门

- [x] 2.1 core/event_bus.py：_recover_done_push_retry 追加 approve_mode 门——get_approve_mode 生效 manual（含缺省回退）且 spec 无推送记账（push_attempts/退避字段双源皆缺）时不投递；有记账的 manual spec 放行续推（已批准重试语义，兼容 push-retry-recovery）
- [x] 2.2 core/event_bus.py：续推门读 entry 的 push_na 持久字段终局跳过（跨重启幂等，重启后零重投递），不推进重试计数、不产生新失败记录

## 3. 分支解析与配置分级

- [x] 3.1 core/pm_engine/engine.py：推送目标分支改为配置优先、缺省按仓库当前分支探测，消除 main 硬编码（approve_push 与归档收口同覆盖）
- [x] 3.2 （回归锁定，无实现改动）pm.push.retry_backoff_seconds 缺失→DEBUG 静默、存在但非法→WARNING 的分级已在既有代码（_handle_push_failure None 例外分支）实现，本项仅补测试锁定该分级（含元素级非法静默回退口径），防回归

## 4. 测试

- [x] 4.1 tests/test_push_git_env_precheck.py：覆盖无 remote/无目标分支的 N/A 短路与持久留痕幂等（重启后零重投递）、manual+零记账拦截续推与 manual+有记账放行续推、非 main 分支解析、缺键静默与非法告警分级回归锁定
- [x] 4.2 tests/test_spec_approve_push.py：既有 _git_push_ref 环境注入用例的临时仓补挂本地 bare remote 让预检放行（否则预检短路使 argv/env 断言失效），断言按 N/A 标记形态适配
