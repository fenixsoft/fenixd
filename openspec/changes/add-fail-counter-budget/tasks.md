# Tasks: add-fail-counter-budget

实现依据（实施 agent 必读）：
- 能力定义 `specs/fail-counter-budget/spec.md`；设计决策 design.md D1-D4
- 计数写点：`.fenix/core/pm_engine.py` 全部 `_verify_fail_rounds` 写点（打回处置约 880-935 行、收工路径的 update_spec 连带覆盖处）
- 派发点：`_run_agent_worker` implementer 分支（预算计数）与重派决策处（打回重派 / `_enqueue_front` 重试）
- 配置：`_get_config` 链路 + config.yaml + Dashboard config 页（新增配置键必须带界面）
- 夹具：v2-config-page 24h 振荡史（00:20 打回日志显示归零的证据）

## 1. 计数语义修正

- [ ] 1.1 审计并移除打回重派 / 修复收工路径上对 `_verify_fail_rounds` 的隐式归零（字段级更新避免连带覆盖 `_retry_count: 0` 等既有字段）
- [ ] 1.2 验证 PASS 采纳处保留唯一归零点；单元测试覆盖「重派保留计数、PASS 归零」

## 2. 实现尝试总预算

- [ ] 2.1 `_impl_run_budget_used` 在 implementer run 启动时递增并持久化；重派决策处校验 `used >= agents.impl_run_budget`（缺省 4）→ blocked + `impl_budget_exhausted` 告警（含 spec、次数、最近失败摘要），已启动 run 照常跑完 merge
- [ ] 2.2 配置键 `agents.impl_run_budget`（config.yaml 缺省注释示例 + `_get_config` 读取 + 热更新生效）

## 3. Dashboard 界面

- [ ] 3.1 config 页新增「实现尝试预算」数值输入（1-10 校验，保存走既有链路），浏览器实测保存与热更新生效

## 4. 单元测试

- [ ] 4.1 覆盖：计数跨修复周期累计到 3 触发冻结（模拟 v2-config-page 振荡序列）；预算 4/4 耗尽冻结与告警内容；已启动 run 收工 merge 不受预算影响；配置热更新生效

## 5. 验证与打包

- [ ] 5.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [ ] 5.2 执行 `bash scripts/package.sh` 生成最新扩展包
