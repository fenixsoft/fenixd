# 验证报告：add-harness-default-key-fallback

> ⚠️ 本报告由框架于 2026-11-03T02:59:16Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-03T02:59:15.717593+00:00+run-result@mtime1793674755769575652

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.06M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dsh-fallback-spawn-no-patch | dsh 无分配回落 spawn：agents.models 无分配（env_overrides 无 provider 链键且 model 空）时 build_spawn_spec 正常返回 SpawnSpec，argv 不含 --patch、系统临时目录零 patch 文件落盘、env 不含 FENIX_DSH_PROVIDER_API_KEY 桥接键；--profile/--json 与反串扰清除（ambient ANTHROPIC_API_KEY 剔除）、DSH_HOME 注入、FENIX_RUN_* 注入、stdin 载荷语义不变；非链 env_overrides（自定义键）仍透传；clean 口径同验（无 FENIX_RUN_*）。不抛 DshSpawnConfigError。证据：core/agent_runner/harness/dsh_adapter.py:715-741（现三要素预检，本 SPEC 放宽）、:89（DSH_API_KEY_ENV）、tasks 1.1/1.2 | pass | 0/11 | - |
| dsh-partial-chain-still-errors | dsh 部分链笔误防护矩阵（裁决原地修复 2026-11-03）：env_overrides 仅含 ANTHROPIC_BASE_URL、仅含 ANTHROPIC_API_KEY、含 baseurl+apikey 但缺 model 三种「配了一半」形态仍抛 DshSpawnConfigError（笔误防护语义不变）；仅设 model（无 env 链键）属无分配回落形态不抛——修复：原矩阵误把该形态纳入必报错集合，与 design Decisions 2「部分链=env_overrides 含任一链键但三要素不全」矛盾（req.model 不参与回落判定，dsh_adapter.py:735-746，无分配车道传钉死模型名回落是本 SPEC 核心语义）；对照：全链三要素齐不抛；链键空白串视为空=无分配回落不抛。证据：spec/changes/add-harness-default-key-fallback/specs/harness-default-fallback/spec.md、design.md Decisions 2 | pass | 0/8 | - |
| dsh-explicit-chain-unchanged | dsh 显式全链形态行为不变（回归红线）：全链 SpawnRequest 产出 argv 含 --patch 且 patch 文件真实落盘、patch 内容渲染 model 与 baseURL 三要素、env 桥接 FENIX_DSH_PROVIDER_API_KEY=apikey、ANTHROPIC_BASE_URL/ANTHROPIC_API_KEY 两 consumed 键不透传子进程、FENIX_RUN_PROJECT_ROOT/WORKTREE 注入（agent-run 口径）、--profile/--json 在位、argv 无裸 headless、stdin 载荷与 cwd 不变；resume 形态 --session-id 严格采纳仍在；patch 登记计数 +1。证据：core/agent_runner/harness/dsh_adapter.py:737-766（现 argv/env 组装）、:764-819（_write_model_patch）、design 回归红线（Goals） | pass | 0/11 | - |
| claude-fallback-spawn-ok | claude 无分配 spawn 成功（对称回落现状保持）：model=None、env_overrides 无链键时 ClaudeAdapter.build_spawn_spec 正常返回，argv 为 claude -p 形态（stream-json 必带 --verbose）、不注入 --model、stdin 载荷为 prompt、env 为 agent-run 口径字典；对照：显式 model 形态 --model 仍注入（本 SPEC 仅加 WARN 钩子，spawn spec 输出不变，快照零改动）。证据：core/agent_runner/harness/claude_adapter.py:347-424（现 build_spawn_spec 无预检）、design Risks（快照零改动） | pass | 0/8 | - |
| fallback-warn-once-per-process | 回落 WARN 观察钩子一次性去重（进程×adapter）：同进程 dsh 连续 3 次无分配 spawn 仅第 1 次产生 WARNING（文案含「未分配」与「回落」语义），3 次均正常返回 SpawnSpec 不拒 spawn；claude 同进程 3 次无分配 spawn 独立去重恰 1 条 WARNING；显式全链 dsh spawn 不再触发新 WARNING；两 adapter 各自至多 1 条（合计 2 条）。若 SpawnRequest 具备角色字段则附加校验 WARNING 含角色名。证据：spec Requirement「回落 WARN 观察钩子（一次性）」、tasks 2.1（进程×adapter 去重）、design Decisions 3 | pass | 0/8 | - |
| metrics-provider-source-marker | 归因降级标记落位：tests/test_harness_default_fallback.py（tasks 3.1 新建）存在且覆盖 metrics 标记两形态断言（文件含 provider_source 与 harness-default 字面）、该测试文件 pytest 全绿；core/agent_runner/runner.py 含 provider_source 接线（tasks 2.2）。证据：tasks.md 2.2/2.3/3.1、core/agent_runner/runner.py:9846-9874（_log_run_metrics metric_ctx 既有形态）、spec Requirement「归因降级标记」 | pass | 0/13 | - |
| harness-regression-green | 既有 harness/dsh 测试全绿回归（显式链形态零回归）：test_harness_dsh_adapter.py/test_harness_adapter.py/test_harness_claude_snapshot.py/test_harness_one_shot_forms.py 四契约文件与 test_dsh_full_chain.py/test_dsh_acceptance.py 端到端回归全部通过（变更前基线 106+44 passed，快照零改动或仅注释级更新）。证据：tasks.md 3.2/3.3、design Risks（快照应零改动）（裁决原地修复 2026-11-03：两步骤 pytest 去掉 -v——-v 逐行列出通过测试名，其中 test_dsh_startup_failed_generic 名字含 failed 子串，使 negate「failed」断言被测试名字面确定性误报；去 -v 后输出只剩进度与汇总行，失败仍产生「N failed」汇总行，断言检测力不降） | pass | 0/8 | - |

## 本轮场景集变更

当前稳定场景集共 7 个（第 1 轮）。

- 首轮写入 7 个场景

