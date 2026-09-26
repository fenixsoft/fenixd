## Deliverables

```yaml
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: tests/test_fasttrack_verification_write_gate.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/agent_runner/result_gate.py：`_check_impl_result_artifact` 在 status 白名单检查后追加 fast-track verification 段校验分支——仅 status 为 success 且 mode 为 fast-track 时调用 core.fast_track_result.parse_fast_track_verification，返回 None 即硬门失败并给出「verification 段缺失或结构不完整」错误；partial/error 状态与 mode 非 fast-track 的结果一律不触发，full 车道行为不变
- [ ] 1.2 core/agent_runner/prompt_builder.py：`_result_gate_section` fast-track 分支补契约句——success 结果文件必须含合法 verification 段（scenarios 非空、每条含非空 scenario_id/description、status 枚举合法、verdict 属 verified/bug-found），与 run 末硬门同一解析口径

## 2. 测试

- [ ] 2.1 tests/test_fasttrack_verification_write_gate.py：覆盖四类场景——缺 verification 段的 fast-track success 结果被硬门拦截、补写合规段后放行、partial/error 诚实退出不误拦、full 车道（mode 非 fast-track）结果不触发
- [ ] 2.2 回归既有 tests/test_agent_runner_gate.py 与 tests/test_fast_track_result.py，确认 full 车道与 dispatch 交接点行为不变