# Tasks: add-recovery-legacy-check

实现依据（实施 agent 必读）：
- 能力定义 `specs/recovery-legacy-check/spec.md`；设计决策 design.md D1-D5
- 挂钩点：`.fenix/core/worktree_manager.py` `refresh_locks`（约 530 行，陈锁释放时刻注册遗产）与清扫回收路径
- 注入点：`.fenix/core/agent_runner.py` implementer prompt 构建处（查询遗产）
- 回收点：`.fenix/core/pm_engine.py` `_run_agent_worker` merge 成功处（consume_legacy）
- 真实夹具：add-fail-counter-budget 恢复现场形态（run 死亡 → ready → 重派）
- 禁止范围蔓延：不做会话续跑、不做智能合并、不加配置键

## 1. 遗产注册与回收

- [ ] 1.1 worktree_manager 新增 `register_legacy(spec, path, branch)` / `get_legacy(spec)` / `consume_legacy(spec)`（内存态 + 审计日志，覆盖式更新仅留最新）
- [ ] 1.2 refresh_locks 释放陈锁时（该锁属 implementer run 且 spec 随后进入恢复重派）注册遗产；清扫器对在册遗产豁免，宽限期超时兜底回收并记审计
- [ ] 1.3 后继 run merge 成功处 consume_legacy 触发回收

## 2. 上下文注入

- [ ] 2.1 implementer prompt 构建处注入「遗产检查」段：路径/分支/脏文件快照（现场 git status 采集，截断 50 行）+ 只读约束 + 收编/弃用决策要求与响应格式
- [ ] 2.2 无遗产时不注入空段（prompt 与现状逐字节一致）

## 3. 单元测试

- [ ] 3.1 覆盖：死亡 run → 遗产注册 → 清扫豁免；后继 merge → 回收；宽限期超时兜底；遗产覆盖式更新；无遗产 prompt 不变
- [ ] 3.2 收编/弃用两路径的 prompt 注入内容断言（含 salvaged from 标注要求）；用 fail-counter-budget 现场形态作夹具

## 4. 验证与打包

- [ ] 4.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [ ] 4.2 执行 `bash scripts/package.sh` 生成最新扩展包
