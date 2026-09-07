# Tasks: fix-provider-transient-backoff

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/agent_runner/session.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SystemPanel.tsx
  kind: modify
- path: docs/help/08-config.md
  kind: modify
- path: tests/test_transient_backoff.py
  kind: new
```

## 1. 错误归因降噪与瞬断判定（error-attribution-denoise）

- [x] 1.1 runner `_run_claude` error 拼装处（现 `runner.py:2427` 附近）：过滤 `^\[claude-code:` 诊断行后再拼接，过滤后为空回退 `Exit code: {returncode}`；jsonl stderr 原始事件保持不过滤
- [x] 1.2 新增瞬断判定函数：全量 stderr_lines 命中 switch 类 pattern（unrecognized_model / 5xx / 连接类）**或**（exit≠0 且本进程无 result 事件且 stderr 存在 `[claude-code:]` 行）→ 判为瞬断；判定不依赖降噪后 error 字符串
- [x] 1.3 单元测试：诊断行过滤、全噪音回退、双通道判定各正反例（tests/test_transient_backoff.py）

## 2. 原地退避与 resume 续跑（provider-transient-backoff）

- [x] 2.1 attempt 循环插入原地重试分支：瞬断判定命中且预算未耗尽 → 写 `transient_retry` 事件（含退避秒数/重试序号）→ sleep `transient_backoff_schedule` 下一档 → 同 provider 重跑该 attempt（run_id 加 `r{n}` 后缀独立产物），不递增 attempt、不触发 switch 冷却、不改 chain_cursor
- [x] 2.2 `r{n}` 子重试的 session 续跑：从上一产物提取 session_id，`_resumable_session_id` 对「同 provider + worktree 复用」的原地重试放行；`No conversation found` 时清 session 全新会话重试，连续 2 次 resume 失败后改全新会话
- [x] 2.3 原地预算耗尽后接现行逻辑：switch 冷却 + chain 前进，下一 provider 同 worktree 新会话
- [x] 2.4 单元测试：原地重试不递增 attempt/不冷却、预算耗尽转换链、resume 死 session 兜底、run_id 后缀产物独立

## 3. worktree 现场保留扩展（provider-transient-backoff）

- [x] 3.1 attempt 间 worktree 保留白名单删除（runner 现保留清单仅 implementer/fast-track/repair），全 agent_type 保留，复用前仍过 frozen/取消检查
- [x] 3.2 transient 终态失败分支：`cleanup(success=False)` 前先判定瞬断 → `keep_for_reuse` 登记（worktree_manager 泛化 agent_type 参数）；非瞬断维持现行清理
- [x] 3.3 下轮派发认领：implementer/planner 族派发经 `_take_reusable_worktree` 认领复用遗产（照 fast-track 既有通道），长期无人认领由既有 stale 清扫兜底
- [ ] 3.4 单元测试：planner-judge attempt 间复用、瞬断终态 keep_for_reuse、非瞬断终态照旧清理、认领继承现场

## 4. dispatch 排程等待与全局熔断（transient-dispatch-gating）

- [x] 4.1 runner 瞬断终态收场时 error 消息头部注入 `[provider-transient]` 结构化标记（写侧统一）
- [x] 4.2 dispatch 失败处理分支识别标记 → 走 `_schedule_transient_recovery`（仿 instant_fail_recovery 定时器模式，`transient_redispatch_delay_seconds` 缺省 600）→ 到期重入派发；跳过 `_retry_count` 递增/清零路径；死亡豁免保持
- [ ] 4.3 provider_circuit 新增全局错误指纹熔断：错误文本归一化指纹（剥 model 名/时间戳）+ 滑动窗口计数（`transient_break_threshold/window/cooldown`，缺省 3/600/600）→ 派发闸门冻结 + major 告警（15 分钟 throttle）；进程内存态
- [ ] 4.4 单元测试：标记注入、排程等待不写 retries exhausted、非 transient 路径逐字节不变、熔断触发/解除/告警节流

## 5. 配置键与 Settings UI（transient-controls-ui）

- [ ] 5.1 `core/config.py`：五个新键定义与校验（`transient_backoff_schedule` 逗号秒序列、`transient_redispatch_delay_seconds`、`transient_break_threshold`、`transient_break_window_seconds`、`transient_break_cooldown_seconds`），非法值回退缺省（防御式先例同 `_shutdown_drain_seconds`）
- [ ] 5.2 `.fenix/config.template.yaml`：新键带注释写入模板（缺省值与 design D6 表一致）
- [ ] 5.3 SystemPanel 新增「瞬断治理」分组：展示/编辑五键，校验与后端一致（非负整数/序列），非法输入拦截提示；保存后配置热更新（30s mtime）生效
- [ ] 5.4 `docs/help/08-config.md` 配置文档补五键语义与缺省值
- [ ] 5.5 前端构建产物重建（框架 merge 后自动重建，验证截图存 `.history`）

## 6. 集成回归与验收

- [ ] 6.1 回归：瞬断重试与秒挂熔断（instant_fail 60s 存活时长判定）交互——原地重试拉长存活不误触发秒挂；与死亡豁免/预算闸门叠加语义不回归
- [ ] 6.2 回归：daemon 重启恢复路径（recover_interrupted）与 keep_for_reuse 遗产认领协同无互删
- [ ] 6.3 全量既有测试套通过（test_provider_circuit / test_provider_failover / test_runner_provider 等零回归）
- [ ] 6.4 真实故障文本 fixture 回放：以 2026-09 死亡 run 的 stderr 样本回放判定与降噪路径（参照 tests/test_provider_failover.py:173 真实故障 fixture 惯例）
