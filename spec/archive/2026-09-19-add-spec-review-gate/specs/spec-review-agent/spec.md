# spec-review-agent — SPEC 方案评审 Agent 本体

## ADDED Requirements

### Requirement: 评审 Agent 提示词文件注册

系统 SHALL 提供评审 Agent 的提示词文件 `agents/spec-review.md`，并将其注册进 `core/agent_runner/prompt_builder.py` 的 `AGENT_PROMPT_FILES` 白名单（类型键 `spec-review`）。提示词模板 SHALL 声明：评审者角色与单轮评审定位、三个评估维度（`goal-fit` / `hole` / `regression`）、输出契约全文、写权限边界、取证义务（结论须引用具体文件路径与位置）、禁止修改 SPEC 目录外任何文件。模板 SHALL 通过 `_fill_placeholders` 支持的占位符接收 `{spec_name}`、`{spec_dir}`、`{result_path}`、`{state_path}` 等上下文，MUST NOT 使用 `str.format` 语法。

#### Scenario: 提示词文件可被加载
- **WHEN** 以类型 `spec-review` 构建 prompt
- **THEN** `_load_agent_template` 成功读出 `agents/spec-review.md` 内容，无 fail-fast 异常

#### Scenario: 未注册类型 fail-fast
- **WHEN** 以未列入 `AGENT_PROMPT_FILES` 的类型键构建 prompt
- **THEN** 加载失败并抛出明确异常，MUST NOT 静默返回空模板

#### Scenario: 占位符被逐字填充
- **WHEN** 构建 prompt 时传入 `spec_name`、`spec_dir`、`result_path`
- **THEN** 占位符被替换为实际值；模板中形如 `{a:>10}` 的花括号内容不被 `str.format` 解析而报错

### Requirement: 评审 Agent 运行范式

评审 run SHALL 采用与 `run_dispute_judge` 相同的判官范式：**不创建 git worktree**，`cwd` 为主树项目根，`claude` 子进程以 `--add-dir <项目根>` 启动。run_id SHALL 形如 `spec-review-<spec>-<ts>`，且该前缀 MUST 同时登记在 `core/agent_runner/run_files.py` 与 `core/admin_monitor.py` 的 `_RUN_PREFIXES` 两处（两处同源，缺一将导致 run 文件与监控口径不一致）。

#### Scenario: 不创建 worktree
- **WHEN** 派发一次评审 run
- **THEN** 运行期间不存在为该 SPEC 新建的 `fenix/<spec>-*` 分支与 worktree 目录；run 的 cwd 为主树项目根

#### Scenario: run_id 前缀双处登记
- **WHEN** 派发一次评审 run 并读取其 run_id
- **THEN** run_id 以 `spec-review-` 开头；`run_files.py` 与 `admin_monitor.py` 的前缀元组均包含该前缀，run 文件可被正常归类与统计

#### Scenario: 模型路由按分配生效
- **WHEN** `agents.models.spec-review` 配置了 provider 链
- **THEN** 评审 run 以链首 provider 的 `ANTHROPIC_BASE_URL / API_KEY / MODEL` 与独立 `CLAUDE_CONFIG_DIR` 启动，并写入 provider marker

#### Scenario: 未分配模型走默认网关
- **WHEN** `agents.models` 中不存在 `spec-review` 项
- **THEN** 评审 run 使用默认网关模型常量启动，不报错

### Requirement: 评审输入可及性

评审 Agent SHALL 能直接读取 SPEC 目录下的 `proposal.md`、`design.md`、`tasks.md` 与 `specs/*/spec.md`。MUST 额外可读 `spec/archive/` 下已归档的历史 SPEC 与 `.fenix/runs/` 下的历史 run 流转录，用于复杂方案的复盘比对。提示词 SHALL 明确告知这些路径的用途，使评审者对复杂方案能主动查阅历史证据而非仅凭 SPEC 自述判断。

#### Scenario: 三文档可读
- **WHEN** 评审 Agent 读取 `{spec_dir}` 下的三份文档
- **THEN** 三份文档均可正常读出内容

#### Scenario: 历史证据可查
- **WHEN** 评审者对某复杂方案需要比对历史实现
- **THEN** 可读取 `spec/archive/` 下的归档 SPEC 与 `.fenix/runs/` 下的 run 流转录；输出 `history_consulted` 字段记录实际查阅过的路径

#### Scenario: 未查阅历史时字段为空
- **WHEN** 评审者判断方案无需比对历史即可定论
- **THEN** `history_consulted` 为空数组，MUST NOT 伪造查阅记录

### Requirement: 评审输出契约

评审 Agent SHALL 将结果写入 `{result_path}`（绝对路径，即 `.fenix/spec-review/<spec>/.fenix-run-result.json`），MUST NOT 写入其它任何路径。结果 JSON 顶层 SHALL 包含：

- `status`：三取一 `approved` / `repaired` / `rejected`
- `summary`：一句话结论
- `findings`：条目数组，每条含 `severity`（`blocking` / `repairable` / `note`）、`aspect`（`goal-fit` / `hole` / `regression`）、`detail`、`evidence`
- `repairs`：条目数组，每条含 `path` 与 `summary`
- `history_consulted`：路径字符串数组
- `confidence`：`high` / `medium` / `low`

`status` 语义 MUST 严格对应：`approved` 表示方案可行且未作改动（此时 `repairs` MUST 为空）；`repaired` 表示方案可行但评审者已就地修补可修补漏洞（此时 `repairs` MUST 非空）；`rejected` 表示存在方向性风险或致命漏洞，需人工裁决（此时 `findings` MUST 至少含一条 `severity: blocking`）。

#### Scenario: approved 且无改动
- **WHEN** 评审者判定方案可行且无需修改
- **THEN** 写入 `status: "approved"`、`repairs: []`，`findings` 仅含 `repairable`/`note` 级条目或为空

#### Scenario: repaired 且自报修补清单
- **WHEN** 评审者就地修补了 tasks.md 中一处任务拆分缺失
- **THEN** 写入 `status: "repaired"`，`repairs` 含 `{"path": "spec/changes/<spec>/tasks.md", "summary": ...}`，`findings` 含对应的 `severity: repairable` 条目

#### Scenario: rejected 且给出阻断项
- **WHEN** 评审者判定方案存在方向性错误
- **THEN** 写入 `status: "rejected"`，`findings` 至少含一条 `severity: "blocking"` 且 `aspect` 取自三维度枚举，`evidence` 引用具体文件路径

#### Scenario: 三维度齐全
- **WHEN** findings 中存在多条条目
- **THEN** 每条 `aspect` 取值均落在 `goal-fit` / `hole` / `regression` 之内，MUST NOT 出现枚举外的值

#### Scenario: 禁止越界写入
- **WHEN** 评审 run 收工
- **THEN** `{result_path}` 之外的路径不存在由本次 run 引入的新增或修改（SPEC 目录内的修补除外）

### Requirement: 评审结果硬门

评审 run 的成功判定 SHALL 复用框架既有硬门 `_check_agent_result_artifact`：进程 exit code 为 0 **且**结果文件存在、非空、为合法 JSON、顶层为对象、`status` 落在评审白名单（`approved` / `repaired` / `rejected`）内、且文件 mtime 未早于本轮派发（新鲜度校验，防陈旧合法文件替本轮放行）。任一不满足 SHALL 判定本轮评审为「未完成」，MUST NOT 按任何结论收口。

#### Scenario: 全部满足判成功
- **WHEN** 评审 run exit 0 且结果文件为新鲜合法 JSON 且 status 在白名单内
- **THEN** 本轮评审判定为成功，进入结论消费

#### Scenario: exit 0 但结果文件缺失
- **WHEN** 评审 run exit 0 但结果文件不存在或为空
- **THEN** 判定本轮评审未完成，MUST NOT 视为 `approved`

#### Scenario: status 越白名单
- **WHEN** 结果文件 `status` 为 `"success"` 或其它白名单外的值
- **THEN** 判定本轮评审未完成，MUST NOT 按白名单外语义收口

#### Scenario: 陈旧文件不被采信
- **WHEN** 结果文件为本 SPEC 上一轮评审遗留的合法文件，本轮 run 未重写它
- **THEN** 新鲜度校验判定失败，本轮评审判定为未完成

### Requirement: 主树写入边界校验

评审 run 在主树运行且持有写权限，框架 SHALL 在派发前与收工后各做一次快照比对以检出越界写入：

- 派发前 SHALL 对 `spec/changes/<spec>/` 下所有文件记录相对路径与内容哈希；SHALL 对 `git status --porcelain` 列出的工作区脏文件记录内容哈希（仅比较状态字符串无法检出「已脏文件又被改动」）。
- 收工后 SHALL 校验：`repairs` 中每条 `path` 均落在 `spec/changes/<spec>/` 目录内；快照差集中 MUST NOT 出现在 `spec/changes/<spec>/` 之外的新增或修改；`status` 与改动一致（`approved` MUST NOT 伴随 SPEC 目录改动；`repaired` MUST 至少伴随一处 SPEC 目录改动且 `repairs` 非空）。

任一校验失败 SHALL 判定本轮评审为「未完成」（等价 `spec-review-agent` 故障），并按 `spec-review-recovery` 的规定处置。

框架 MUST NOT 自动回滚越界改动——快照恢复在「主树常存未提交工作」的现实下可能损毁人工在途修改。越界处置 MUST 为「停止自动化 + 记录越界文件清单供人工处置」。

#### Scenario: 合法修补不触发越界
- **WHEN** 评审者仅修改 `spec/changes/<spec>/tasks.md` 且 `status` 为 `repaired`、`repairs` 为该文件
- **THEN** 三项校验全部通过，评审判定为成功

#### Scenario: 越界写入被检出
- **WHEN** 评审 run 修改了 `core/pm_engine/engine.py`
- **THEN** 快照差集检出 SPEC 目录外的新增修改，本轮判定为未完成，越界文件清单记入错误信息

#### Scenario: repairs 路径越界
- **WHEN** `status` 为 `repaired` 且 `repairs` 中某条 `path` 落在 `spec/changes/<spec>/` 之外
- **THEN** 校验失败，本轮判定为未完成

#### Scenario: approved 却改了文件
- **WHEN** `status` 为 `approved` 但快照差集显示 SPEC 目录内存在改动
- **THEN** 校验失败，本轮判定为未完成

#### Scenario: 不自动回滚
- **WHEN** 检出越界写入
- **THEN** 越界文件内容保持原样不被自动还原，仅记录清单并停止自动化
