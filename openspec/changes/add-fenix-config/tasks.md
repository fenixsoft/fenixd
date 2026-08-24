# Tasks: LLM 模型分配与审批模式配置

## 1. 配置 Schema 与加载校验

- [x] 1.1 在 `core/config.py` 新增 `llm.providers` / `agents.models` / `gates.approve_mode` 字段校验（存在时校验：providers 为 list、每项 name/baseurl/apikey 非空且 name 唯一；agents.models 键为已知 agent_type 且 provider 引用已定义 Provider、model 非空；approve_mode ∈ {manual, auto}）；REQUIRED_KEYS 保持不变以兼容旧配置
- [x] 1.2 新增配置读取辅助：`get_agent_model_assignment(agent_type)`（返回 `(provider_dict, model)` 或 `None`）、`get_approve_mode()`（默认 `"manual"`）
- [x] 1.3 在 `config.template.yaml` 同步新增 `llm.providers`（带注释示例）、`agents.models`、`gates.approve_mode` 骨架与说明

## 2. Agent 运行时模型路由

- [x] 2.1 在 `agent_runner.py` 让 `_execute_agent`/`_run_claude` 按 agent_type 解析模型分配：已分配则注入 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` 环境变量，`--model` 取 `provider.sdk_model or agents.subagent_model`（官方名校验）；未分配则完全维持现状
- [x] 2.2 确保 `_build_prompt` 与运行层透传正确 agent_type（implementer / planner-plan / planner-judge / verifier），且多 agent_type 并发时环境覆盖互不串扰（每线程独立 env 副本）

## 3. 自动审批

- [x] 3.1 在 `core/pm_engine.py` 新增 `_auto_approve(spec_name)`：解析分支（STATE.md `branch` 字段优先，否则 `{worktree.implement_branch_prefix}/{spec_name}`），在 project_root 执行 `git push origin <branch>`（subprocess + 超时），成功则 `transition(spec_name, "pushed")` 并写 PROJECT_LOG，失败则保留 done 并记录 error
- [x] 3.2 在 SPEC 到达 `done` 的路径（`_on_spec_done` 及已验证转 done 路径）接入：`approve_mode == "auto"` 且状态非 pushed 时触发 `_auto_approve`，并保证重复扫描不重复推送

## 4. Dashboard 配置端到端

- [ ] 4.1 在 `core/dashboard/server.py` 新增 `GET /api/config?project=<name>`（返回该项目的 `llm` / `agents.models` / `gates.approve_mode` 等受管配置）与 `POST /api/config?project=<name>`（校验请求体大小与项目归属 → 校验配置 → 原子写回 `.fenix/config.yaml`，仅更新受管键，其余键原样保留；校验失败返回 400 不写盘）
- [ ] 4.2 在 `core/dashboard/data.py` 新增配置读取/合并/原子写入辅助函数（含写回时保留头部说明注释块）
- [ ] 4.3 在 `core/dashboard/static/` 新增「配置」页前端：Provider 列表（增删改）、Agent 模型分配下拉（未分配 / provider+model）、审批模式单选（auto 选中时显示真实推送风险提示），保存后提示「配置已保存，重启 daemon 后生效」；导航与样式与现有 Dashboard 一致

## 5. 文档与 Skill 同步

- [ ] 5.1 更新 `skills/fenix-approve/SKILL.md`：说明 auto 模式下 SPEC 已完成自动推送，人工门禁可跳过
- [ ] 5.2 更新 `skills/fenix-status/SKILL.md` / `fenix-dashboard/SKILL.md`：状态概览或 Dashboard 展示当前审批模式与模型分配

## 6. 测试与验证

- [ ] 6.1 在 `tests/test_core.py` 新增单元测试：配置解析与校验（合法/非法/旧配置缺省）、`get_agent_model_assignment` 返回值、`get_approve_mode` 默认值、agent_runner 对已分配/未分配 Agent 的 env 注入与 `--model` 选择
- [ ] 6.2 新增/更新自动审批测试：mock `git push` 成功 → 状态到 pushed；失败 → 保留 done 且记录 error；已 pushed 不重复触发
- [ ] 6.3 运行 `python3 -m pytest tests/ -q` 全量通过，无回归
- [ ] 6.4 端到端验证 Dashboard：启动 dashboard，GET /api/config 返回当前配置；POST 修改审批模式与 Provider 后配置文件正确更新且其它键不变；重启 daemon 后新配置生效；人工确认 auto 模式下 SPEC 到达 done 后自动 push 并标记 pushed
