## Deliverables

```yaml
- path: core/agent_runner/harness/dsh_adapter.py
  kind: new
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/session.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_env_keys.py
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: tests/test_harness_dsh_adapter.py
  kind: new
- path: tests/test_dsh_projection.py
  kind: new
```

## 1. DshAdapter 骨架

- [ ] 1.1 core/agent_runner/harness/dsh_adapter.py 的 build_spawn_spec：argv `dsh headless --json [--session-id fenix-<run_id>]`、prompt 经 stdin 载荷、cwd=worktree、模型经 Bundle 配置显式渲染（provider 链 name/baseurl/apikey/model）
- [ ] 1.2 process_patterns()（dsh 进程识别 pattern）与 capabilities()（按 SPEC-2 探针结论填 task_tools/resume/批内并行判定）
- [ ] 1.3 agent_env_keys.py 扩充 dsh 通道 banned env 键集（ANTHROPIC_* 等防串扰），dsh_adapter env 段应用
- [ ] 1.4 单测（tests/test_harness_dsh_adapter.py）：spawn 契约快照（argv/stdin/cwd/env 断言）

## 2. 投影层（含可观测性三件套）

- [ ] 2.1 normalize_event 投影表实现：session→init（session_id+tools）、text/thinking/tool_call/tool_result→claude 形状、final→result（output/num_turns/usage 形状）、error→error；truncated 透传；num_turns 由 turn_end 计数；未知类型忽略+计数不中断
- [ ] 2.2 可观测性三件套：原始 dsh 事件 dump 落 run 目录旁路文件；投影管线逐级计数（各类型 收到/投影/忽略）；坏事件分类统计（JSON 解析失败/未知类型/超限截断）——全部落 run_metrics 结构化日志
- [ ] 2.3 fixtures 回放测试（tests/test_dsh_projection.py）：以 dsh-bundle/tests/fixtures/headless-events.jsonl 为契约源，投影后 run_task_track 解析出 1 基 taskId 进度、liveness 终态判定正确、result_gate 读侧不受影响
- [ ] 2.4 失败语义测试：exit 1 + turn_end(aborted) 与 error-无-final 两形态投影后均为可终判末行，无悬挂在飞

## 3. stderr 分类接口化

- [ ] 3.1 provider_circuit 分类器按 adapter 分派：claude 实现为现有文本模式平移（行为零变化）、dsh 实现按 SPEC-2 错误码表映射现有分类枚举；熔断/瞬断/记账治理零改动
- [ ] 3.2 测试：dsh 限流错误→ratelimit 并走既有熔断退避路径；claude 既有 stderr 用例回放分类结果全等（快照）

## 4. session 与 usage

- [ ] 4.1 session 绑定：`fenix-<run_id>` 命名空间生成、--session-id resume、provider 指纹绑定与跨 provider 禁止；采纳失败（未知 id/被持有/cwd 不符）回退新 session 重跑并留痕
- [ ] 4.2 extract_result：session_id/num_turns/final 文本提取；usage 按 SPEC-2 探针结论分支（不可得→metrics 标 `usage_source: unavailable` 降级，不伪造数值）
- [ ] 4.3 测试：resume 失败回退不悬挂、usage 降级标记落 metrics

## 5. 健康检查与工厂注册

- [ ] 5.1 harness/__init__.py 工厂注册 dsh；dispatch 前健康检查：`dsh --version` 白名单（钉 dsh-bundle README 版本兼容表的 release）+ Bundle 挂载探测，错误信息含修复指引
- [ ] 5.2 测试：未装 dsh/版本不符 fail-fast 且无 run 被代跑；就绪后 `agent.harness: dsh` 全链 spawn dsh 进程、attempt 环/监督/终态收口按归一化事件运转

## 6. prompt harness_notes 参数化

- [ ] 6.1 prompt_builder.py：_noninteractive_contract_section 与模板 harness 行为描述收敛为 {harness_notes} 占位符，adapter 注入（claude=现状原文、dsh=headless 行为模型）；Task 工具族契约段一字不改
- [ ] 6.2 agents/implementer.md 长任务等待节改 {harness_notes} 占位符注入
- [ ] 6.3 快照测试：claude 通道组装 prompt 与改造前逐字节一致；claude/dsh 两通道同车道 prompt 差异仅落在 harness_notes 段

## 7. 收尾验证

- [ ] 7.1 端到端冒烟：DSH_HOME 隔离 + 假模型端点下 `agent.harness: dsh` 跑通 dispatch→在飞判定→终态收口→result gate 全链（含可观测性三件套产物核对）
- [ ] 7.2 全量回归绿 + 编译自洽；全仓 grep 核查 dsh 硬编码仅存在于 harness/dsh_adapter.py
