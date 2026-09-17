## Deliverables

```yaml
- path: core/config.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify    # 补齐 agents.timeout_supervision 受管子键，使自动对齐值可经既有写路径持久化
- path: fenixd.py
  kind: modify    # 启动（initialize）与热更新（_maybe_reload_config）接入自动对齐/阻断与持久化调用
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_supervision_timeout_consistency.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/config.py：新增单一派生函数 `supervision_floor(config, agent_type=None, extension_budget=None)`（下限 = 生效 run_timeout（含 per-agent 覆盖）+ 续期预算 × extension_seconds）；`effective_supervision_absolute_max_seconds` 消费之，删除手写 `SUPERVISION_EXTENSION_SECONDS = 7200` 常数（改为按最大续期预算派生）；配置校验层（`_validate`）按**全部署最大可达下限**判定：`max(全局 run_timeout, 全部 timeout_overrides) + (max_extensions + 2) × extension_seconds`（当前配置 = 15000 + 4×1800 = 22200s）
- [ ] 1.2 core/agent_runner/liveness.py：liveness.py:777-789 兜底口径改调同一派生函数（传入该 agent 实际预算，fast-track higher 档 `max_extensions + 2`），删除手写 `floor_absolute_max` 表达式；**运行时数值不变**（基础档 18600s / fast-track higher 档 22200s）
- [ ] 1.3 core/config.py + fenixd.py：一致性校验接入启动（resolve_config）与热更新（resolve_config_into）两条路径；默认自动对齐（ERROR 含两侧值/下限/修正建议 → 抬升 absolute_max 至下限 → 内存生效并持久化，MUST NOT 抛异常）；显式关闭对齐时 fail-fast（启动失败；热更新沿用既有 try/except + 失败不触碰旧值语义拒绝并回滚）
- [ ] 1.4 core/dashboard/data/config_admin.py + fenixd.py：自动对齐持久化复用既有写路径 `core.dashboard.data.write_config`（补 `_AGENTS_MANAGED_SUBKEYS` 的 `agents.timeout_supervision` 受管子键；core/config.py MUST NOT 直写配置文件）
- [ ] 1.5 .fenix/config.template.yaml：absolute_max_seconds 注释对齐约束（≥ max(生效超时) + (max_extensions + 2) × extension_seconds）并给出示例值

## 2. 测试

- [ ] 2.1 tests/test_supervision_timeout_consistency.py：派生值正确——运行时基础档 15000+2×1800=18600、fast-track higher 档 15000+4×1800=22200；配置校验层最大下限 15000+4×1800=22200
- [ ] 2.2 tests/test_supervision_timeout_consistency.py：config 校验层与 liveness 兜底层调用同一派生实现（断言同函数/同值），无手写常数残留
- [ ] 2.3 tests/test_supervision_timeout_consistency.py：absolute_max < 配置层下限 → 默认自动对齐（ERROR 含两侧值与下限、抬升至 22200、无阻断）；显式关闭对齐 → 启动阻断（fail-fast）
- [ ] 2.4 tests/test_supervision_timeout_consistency.py：热更新不一致 → 对齐持久化后无 ERROR；关闭对齐 → 拒绝新配置并回滚旧值
- [ ] 2.5 回归：tests/test_config.py、test_system_settings_config.py、test_liveness_hang_discrimination.py、test_run_lifecycle_hardening.py、test_run_lifecycle_governance.py 通过（运行时封顶数值不发生变化的证据）
