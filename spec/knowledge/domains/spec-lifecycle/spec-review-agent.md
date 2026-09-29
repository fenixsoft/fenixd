# 方案评审 Agent 本体（spec-review run）
<!-- knowledge: capability=spec-review-agent rev=1
     sources=spec/archive/2026-09-19-add-spec-review-gate -->

评审 run 的 agent 侧契约：提示词注册、判官式运行范式、输入可及性、结果 JSON 契约、结果硬门与主树写入边界。

## 规则

- 提示词文件 `agents/spec-review.md` 注册进 `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` 白名单（类型键 `spec-review`）；模板声明评审者角色与单轮定位、三个评估维度（`goal-fit` / `hole` / `regression`）、输出契约全文、写权限边界、取证义务（结论引用具体文件路径与位置）、禁止修改 SPEC 目录外任何文件；以未注册类型构建 prompt 时 fail-fast 抛异常，不静默返回空模板。
- 占位符经 `_fill_placeholders` 接收 `{spec_name}`、`{spec_dir}`、`{result_path}`、`{state_path}` 等上下文，不使用 `str.format` 语法。
- 运行范式与 `run_dispute_judge` 相同：不创建 git worktree，`cwd` 为主树项目根，`claude` 子进程以 `--add-dir <项目根>` 启动；run_id 形如 `spec-review-<spec>-<ts>`，前缀同时在 `core/agent_runner/run_files.py` 与 `core/admin_monitor.py` 的 `_RUN_PREFIXES` 两处登记（两处同源，缺一导致 run 文件与监控口径不一致）。
- 模型路由：`agents.models.spec-review` 配置 provider 链时按链首 provider 的 `ANTHROPIC_BASE_URL / API_KEY / MODEL` 与独立 `CLAUDE_CONFIG_DIR` 启动并写 provider marker；未分配时走默认网关模型常量，不报错。
- 输入可及性：SPEC 目录下的 `proposal.md`、`design.md`、`tasks.md`、`specs/*/spec.md` 直接可读；额外可读 `spec/archive/` 已归档历史 SPEC 与 `.fenix/runs/` 历史 run 流转录用于复盘比对；提示词告知这些路径用途；输出 `history_consulted` 记录实际查阅过的路径，未查阅时为空数组，不伪造记录。
- 结果契约：结果写入 `{result_path}`（即 `.fenix/spec-review/<spec>/.fenix-run-result.json`），不写其它任何路径。顶层字段：`status`（三取一）、`summary`（一句话结论）、`findings`（数组，每条含 `severity`（blocking/repairable/note）、`aspect`（goal-fit/hole/regression）、`detail`、`evidence`）、`repairs`（数组，每条含 path 与 summary）、`history_consulted`、`confidence`（high/medium/low）。
- status 语义严格对应：`approved` 表示方案可行且未作改动（`repairs` 必须为空）；`repaired` 表示方案可行但已就地修补可修补漏洞（`repairs` 必须非空）；`rejected` 表示存在方向性风险或致命漏洞需人工裁决（`findings` 至少一条 `severity: blocking`）。
- 结果硬门：复用框架既有 `_check_agent_result_artifact`——进程 exit 0 **且**结果文件存在、非空、合法 JSON、顶层为对象、`status` 在评审白名单内、文件 mtime 不早于本轮派发（新鲜度校验，防上一轮遗留的合法文件替本轮放行）；任一不满足判定本轮评审「未完成」，不得按任何结论收口。
- 主树写入边界校验：派发前对 `spec/changes/<spec>/` 全部文件记录相对路径与内容哈希、对 `git status --porcelain` 脏文件记录内容哈希（仅比状态字符串检不出「已脏文件又被改动」）；收工后校验 `repairs` 每条 path 落在 SPEC 目录内、快照差集不出 SPEC 目录外的新增或修改、`status` 与改动一致（approved 不得伴随目录改动；repaired 必须至少一处目录改动且 repairs 非空）；任一失败判本轮「未完成」，按 spec-review-recovery 处置。
- 越界改动不自动回滚：快照恢复在「主树常存未提交工作」的现实下可能损毁人工在途修改；越界处置为停止自动化 + 记录越界文件清单供人工处置。

## 溯源

- [2026-09-19 2026-09-19-add-spec-review-gate](spec/archive/2026-09-19-add-spec-review-gate/) — 新增评审 agent 契约：提示词注册与占位符、判官范式与 run_id 双处登记、模型路由与输入可及性、结果 JSON 契约、结果硬门与主树写入边界（含不自动回滚裁定）
