## Deliverables

```yaml
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: agents/evolution.md
  kind: modify
- path: tests/test_evolution_bg_wait_ceiling.py
  kind: new
```

## 1. evolution 车道 env 注入

- [ ] 1.1 core/agent_runner/maintenance_runs.py：在 run_evolution 的 env_overrides 组装处（现约 :964-977）注入 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0"，仅作用于 evolution 车道；不改动 core/agent_runner/runner.py 的全局 env 构造（CLAUDE_CODE_ENABLE_TODO_TOOLS 等全局注入位保持不变）
- [ ] 1.2 core/agent_runner/maintenance_runs.py：对 run_self_review / run_code_review 等「派子代理等汇总」型同构车道实测评估是否同样存在 600 秒击杀暴露，把「注入/不注入」的决策与理由以注释留痕；默认不改其行为

## 2. 进化提示词兜底约束

- [ ] 2.1 agents/evolution.md：在「执行模式」节（派子代理相关条目附近）追加约束——核查子代理 MUST 前台派发（同一回合内等待结论返回再继续）；收齐全部子代理结论前 MUST NOT 结束回合；每写完一条分片立即并入产物（与现行分片写入步骤表述一致）

## 3. 上限击杀失败归因增强

- [ ] 3.1 core/agent_runner/maintenance_runs.py：在 evolution 收尾契约缺失置 success=False 的分支（现约 :1022-1031）增加嗅探——读本 run 转录文件尾部若干 type: stderr 行，命中「Background tasks still running after 600s」子串（大小写不敏感）时，向失败 reason 追加「CLI 后台等待 600 秒上限击杀（CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS），子代理半成品随 run 作废」说明；转录不可读时静默跳过

## 4. 测试

- [ ] 4.1 tests/test_evolution_bg_wait_ceiling.py：断言 run_evolution 组装的 env_overrides 含 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0" 且其他维护车道（任取一对照车道）组装的 env_overrides 不含该键
- [ ] 4.2 tests/test_evolution_bg_wait_ceiling.py：单测归因嗅探——构造含 600 秒 stderr 签名的伪转录与产物缺失契约，断言失败 reason 含上限归因文案；构造无签名场景，断言 reason 维持原文案