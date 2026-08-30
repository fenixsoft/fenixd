# Tasks: add-implementer-deliverable-gate

实现依据（实施 agent 必读）：
- 能力定义 `specs/implementer-deliverable-gate/spec.md`；设计决策 design.md D1-D4
- 插入点：`.fenix/core/pm_engine.py` `_run_agent_worker` 的 `is_success` 分支（零变更哨之后、`merge_back_from_branch` 之前）
- 重试机制复用零变更哨路径：`_retry_count` + error 注明 + `_enqueue_front` 重派 + 3 次封顶 blocked
- 真实夹具：`openspec/changes/v2-config-page/`（事故现场文档）

## 1. 提取器

- [ ] 1.1 新增 `.fenix/core/deliverables.py`：`extract_paths(spec_dir) -> list[str]`，按 D2 规则提取（反引号/代码块/路径前缀行，匹配 core|tests|.fenix|scripts 前缀，去重、排除绝对路径与目录条目）
- [ ] 1.2 单测：从 v2-config-page 真实文档提取出 config.json 等预期路径；空文档/无路径文档返回空列表

## 2. 收工守卫接入

- [ ] 2.1 `_run_agent_worker` 成功分支插入守卫：提取 → worktree 内逐路径 stat → 全存在放行；缺件走失败收工（不 merge、`_retry_count` 递增、error 记「交付物守卫：缺件 [...]」、status ready + `_enqueue_front` 重派、3 次封顶 blocked + 升级告警）
- [ ] 2.2 重派 run 的 prompt 构建处注入上轮 error（agent_runner 任务书上下文），agent 可直接定位缺件
- [ ] 2.3 无路径 SPEC 跳过守卫（行为与现状一致）

## 3. 单元测试

- [ ] 3.1 覆盖：缺件阻断（不 merge、状态 ready、error 含缺件清单）；全存在放行（merge 照常）；无路径跳过；3 次封顶 blocked + 告警
- [ ] 3.2 守卫零成本断言：mock 确认校验路径上无 LLM/测试/网络调用

## 4. 验证与打包

- [ ] 4.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [ ] 4.2 执行 `bash scripts/package.sh` 生成最新扩展包
