# 验证报告：add-fenix-dsh-bundle

> ⚠️ 本报告由框架于 2026-10-13T08:29:44Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-13T08:18:27.240143+00:00+run-result@mtime1791880167992998952

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 5/20 场景通过，15 失败，0 错误（1 个真实产品 Bug）**

20 场景：5 pass、10 product-bug（同一 critical 根因级联：bundle 纯 TS 源交付无法被 dsh 加载，ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING）、5 test-defect（场景文件缺陷，已原地修复待重执行）。判 verified 的缺口：仅 1 个产品缺陷（bundle 加载形态）——修复产物形态后 10 个级联场景与 2 个依赖真实加载的场景修复项应可全绿。

| 指标 | 数量 |
| --- | --- |
| 通过 | 5 |
| 失败 | 15 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 11.43M |
| 本链增量 Token（输出） | 0.17M |


## 真实产品 Bug

### BUG-01（severity=critical）· json_output（headless 会话启动失败级联：exit 非 0 / 无 final / 无 tool_call）

- 关联场景：dsh-bundle-isolated-load、dsh-task-tools-one-based-ids、dsh-task-tools-update-event-projection、dsh-task-tools-get-list-and-empty、dsh-task-tools-invalid-inputs、dsh-guard-main-tree-write、dsh-guard-no-env-passthrough、dsh-guard-image-read、dsh-approval-headless-unattended、dsh-agents-md-system-prompt-load
- 描述：dsh-bundle 以纯 TypeScript 源码交付（package.json main/exports 直指 src/*.ts），经 file: 依赖装入 profile 的 node_modules 后 Node ESM loader 拒绝加载（ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING：不支持对 node_modules 下文件做 type stripping），fenix-model-config / fenix-dsh-bundle / fenix-approval 三插件全部 failed to import，dsh 以 StartupError 退出（1 required plugin did not activate）——挂载 Bundle 的 headless 会话全部无法启动，10 个场景零 tool_call、零 final。
- 根因：Bundle 缺少可被 Node 直接加载的 JS 产物（无构建/编译步骤，exports 指向 .ts 源）；spec 要求 Bundle 能被 dsh 真实加载链路挂载使用，TS 源形态在 node_modules 安装场景下结构性不可用。需提供 dist 编译产物（tsc）并将 main/exports 指向产物，或在装配链内提供受支持的 TS 加载机制。
- 证据（场景 dsh-bundle-isolated-load 结构化证据，引用）：
  - failed_assertions: [{"type": "json_output", "selector": "headless_exit_ok", "expected": true, "actual": false}, {"type": "json_output", "selector": "headless_final_ok", "expected": true, "actual": false}, {"type": "json_output", "selector": "tools_has_taskcreate", "expected": true, "actual": false}]
  - screenshots: []
  - first_failed_step: 步骤 e2e：headless 冒烟会话启动失败（dsh_exit 非 0、无 final 事件）


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dsh-verify-infra-helpers | 验证基础设施：落盘共享假模型端点脚本（Anthropic Messages SSE 流式、脚本化 turns、system prompt 捕获），供后续 dsh 驱动类场景复用。出处：本机探针实测 dsh 0.2.0-rc.2 headless 契约（DEEPSEEK_BASE_URL env 路由 + SSE 流式响应）。 | pass | 0/4 | - |
| dsh-bundle-manifest-pinning | Bundle 骨架静态契约：package.json 声明 dsh.bundle（patch 指向覆盖层）、dsh.profile 文件存在且列出 Bundle、cordis.patch.yml 为可解析覆盖层、peerDependencies 全部钉 0.2.0-rc.2、运行依赖仅官方 @deepseek-ai/* 包、README 含版本兼容说明与安装/卸载命令、src/index.ts 装配入口存在。出处：spec.md「Bundle 骨架与版本钉扎」+ tasks.md 2.1 交付物清单。 | failed（已修正） | 1/8 | test-defect |
| dsh-model-config-schema-docs | 模型配置静态契约：src/modelConfig.ts 实现含「模型未显式配置」错误文案与 baseurl/apikey/model 三要素 schema；README 载明配置 schema（供 SPEC-3 provider 链渲染）。出处：spec.md「模型显式配置契约」+ tasks.md 5.2。 | pass | 0/4 | - |
| dsh-bundle-vitest-suite | Bundle 自带 vitest 单测全绿：dsh-bundle 内 pnpm install 后运行 vitest 套件退出码 0（覆盖 tasks 3.3 taskTools、4.3 guards、5.3 审批/模型配置单测的实现方自证）。环境依赖（npm registry 可达）有 fallback: pnpm 本地 store 缓存 prefer-offline。出处：tasks.md 3.3/4.3/5.3/7.1。 | failed（已修正） | 1/3 | test-defect |
| dsh-agents-md-symlink | AGENTS.md 约定载体静态契约：仓库根 AGENTS.md 为指向 CLAUDE.md 的软链（单一真相源），读取内容与 CLAUDE.md 完全一致。出处：spec.md「AGENTS.md 约定载体」+ design.md 决策 5。 | failed（已修正） | 2/5 | test-defect |
| dsh-probe-findings-complete | 真机探针结论沉淀齐备：dsh-bundle/docs/probe-findings.md 覆盖五项（headless --json 事件流样本、stderr 错误码→provider_circuit 分类映射、usage 形态结论含 usage_source/降级路径、原生能力盘点含 dsh-tool-todo/subagent/skill/hooks-claude-code 复用 vs 自研判定、母设计 §4.3 投影表修正建议）并记录 8KiB/32KiB 截断边界；tests/fixtures/headless-events.jsonl 为真实事件流且 session/text/tool_call/tool_result/final 各类型至少一例。出处：spec.md「真机探针结论沉淀」+ tasks.md 1.1-1.5。 | pass | 0/9 | - |
| dsh-bundle-isolated-load | DSH_HOME 隔离加载：隔离目录创建自定义 profile 挂载 dsh-bundle，--dump-config 可见 Bundle 条目，headless 假端点冒烟按契约退出（final 事件产出），TaskCreate 出现在会话工具表，真实 ~/.dsh 零写入。出处：spec.md「DSH_HOME 隔离加载」+ 本机探针 profile 形态实测。 | failed（已修正） | 3/7 | product-bug |
| dsh-bundle-peer-version-mismatch | peer 版本不符 fail-fast：复制 bundle 并把其 @deepseek-ai/* peer 范围改为 ^9.9.9 后挂载，加载以明确版本不兼容错误失败（stderr 明示 peerDependencies 对照），且 bundle 工具未注册（TaskCreate 调用得 unknown tool 错误）——不静默降级。出处：spec.md「peer 版本不符 fail-fast」+ dsh-app-boot README peer 运行时版本检查。 | pass | 0/3 | - |
| dsh-task-tools-one-based-ids | Task 工具族 1 基创建序：同一 headless 会话内假模型连续 TaskCreate 三条任务，tool_result 依次呈现 taskId 1、2、3（Task #1/#2/#3 created 语义）。出处：spec.md「1 基创建序」+ core/run_task_track.py:305 读侧硬约定。 | failed（已修正） | 2/3 | product-bug |
| dsh-task-tools-update-event-projection | 状态更新事件可投影：TaskCreate 后 TaskUpdate 置 completed，tool_call 事件 name=TaskUpdate、input 含整数 taskId=1 与 status=completed，字段名与 claude tool_use block 语义对齐（可被母设计 §4.3 投影表直接消费）。出处：spec.md「状态更新事件可投影」+ docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md §4.3。 | failed（已修正） | 5/6 | product-bug |
| dsh-task-tools-get-list-and-empty | TaskGet/TaskList 可用与空状态：创建前 TaskList 返回空列表（完成状态、非错误——空状态覆盖）；TaskCreate 后 TaskGet(1) 返回所建任务 subject；TaskList 包含该任务。出处：spec.md Task 工具族等价 + 场景覆盖规则空状态条目。 | failed（已修正） | 5/6 | product-bug |
| dsh-task-tools-invalid-inputs | Task 工具参数校验失败路径：TaskUpdate 不存在的 taskId=99 返回工具错误结果；TaskCreate 空 input（缺 subject）被参数校验拒绝。出处：tasks.md 3.3 参数校验失败路径 + spec.md Task 工具族等价。 | failed（已修正） | 2/3 | product-bug |
| dsh-guard-main-tree-write | 主树写守卫：设置 FENIX_RUN_PROJECT_ROOT/FENIX_RUN_WORKTREE 后，headless 会话（全放行审批）写主树文件被阻断且错误含主树只读语义、主树磁盘无落盘（守卫先于审批生效）；写 worktree 内路径放行；写主树 .fenix/verify-progress 白名单路径放行。出处：spec.md「主树写入被拦截」+ .fenix/hooks/block-main-tree-write.py 判定语义。 | failed（已修正） | 4/6 | product-bug |
| dsh-guard-no-env-passthrough | 无 env 守卫不误伤：未设置两个 FENIX_RUN_* env 时，对同样主树路径的写入直接放行落盘（等价 block-main-tree-write.py 无 env 直通行为）。出处：spec.md「无 env 时守卫不误伤」。 | failed（已修正） | 2/3 | product-bug |
| dsh-guard-image-read | 读图拦截：headless 会话 read 文本文件放行；read .png 图片目标被阻断且错误含「不支持图像输入」语义（对齐 block-image-read.py 的 Read matcher 语义）。出处：spec.md 三守卫等价 + .fenix/hooks/block-image-read.py。 | failed（已修正） | 2/3 | product-bug |
| dsh-guard-scenario-batching | 场景批处理守卫：首次 Write 带肉（非空 steps）的 test_scenarios.json 被阻断；文件已存在后的重写放行；写非场景路径放行（对齐 planner-scenario-batching.py 的 Write matcher 语义）。出处：spec.md 三守卫等价 + .fenix/hooks/planner-scenario-batching.py。 | failed（已修正） | 4/5 | test-defect |
| dsh-approval-headless-unattended | 非交互审批全放行：headless 会话执行守卫放行路径的 bash 工具调用直接执行（无交互确认等待），产物落盘、final 事件产出、进程按契约退出——等价 bypassPermissions 无人值守零阻塞。出处：spec.md「无人值守不阻塞」。 | failed（已修正） | 4/5 | product-bug |
| dsh-model-config-missing-model-fails | 模型显式配置契约：patch 配置提供 baseurl/apikey 而缺 model 时，会话创建以「模型未显式配置」错误失败；本场景不设 DEEPSEEK_* env，若回退 dsh 默认档即视为违约。出处：spec.md「缺 model 配置即拒绝启动」+ design.md 决策 4（narrative 网关别名事故承袭）。 | failed（已修正） | 1/3 | test-defect |
| dsh-agents-md-system-prompt-load | system-prompt 分区装载一致：含 marker 文本的工作区 CLAUDE.md（经 AGENTS.md 软链）在挂载 Bundle 的 headless 会话中进入 LLM 请求 system prompt（假端点捕获请求体验证 marker 与正文均在）——与 claude 通道注入等价；本机探针实证 dsh 原生不含工作区 CLAUDE.md，marker 出现即 Bundle 分区生效。出处：spec.md「装载内容一致」。 | failed（已修正） | 3/4 | product-bug |
| dsh-probe-stderr-error-codes | stderr 错误码形态真机取证：不可达模型端点（127.0.0.1 死端口）下 headless 运行以非零退出失败，stderr 呈 dsh: <CODE>: <message> 形态，样本留存供 probe-findings 错误码表对账。出处：tasks.md 1.2 + spec.md 探针要求；形态来自本机探针实测（dsh: STREAM_CLOSED: ...，exit 1）。 | pass | 0/5 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| dsh-bundle-manifest-pinning | json_output peer_pinned_ok | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言写宽：cordis 为 4.x 线无 0.2.0-rc.2 版本，实际钉 ~4.0.4 正确（install.log 证 4.0.4 解析安装成功无冲突），dsh/dsh-app-boot/dsh-tools 三包实钉 0.2.0-rc.2；场景文件缺陷 |
| dsh-bundle-vitest-suite | json_output install_ok | test-defect | 测试用例自身缺陷（非产品缺陷） | pnpm v10 默认拒绝依赖构建脚本并以 ERR_PNPM_IGNORED_BUILDS 使 install 退出非 0；依赖实装 +578 done、tests_passed=true。场景命令未适配 pnpm v10 审批语义，场景文件缺陷 |
| dsh-agents-md-symlink | json_output is_symlink | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言口径过时：实体文件(100644)为已批准验收偏差（commit 1a7e1bf2 软链(120000)改实体文件、4bffac0b sha256 全等复核）；场景文件仍按软链旧口径断言 |
| dsh-agents-md-symlink | json_output points_to_claude_md | test-defect | 测试用例自身缺陷（非产品缺陷） | readlink 不适用于实体文件，断言随旧软链口径失效；content_identical=true 实测通过，实体文件形态已达标 |
| dsh-guard-scenario-batching | json_output first_fleshed_write_blocked | test-defect | 测试用例自身缺陷（非产品缺陷） | 假端点未启动（state.json 非法 JSON），守卫行为未被测到：stderr 报 fake_llm.py JSONDecodeError |
| dsh-guard-scenario-batching | json_output skeleton_rewrite_allowed | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上，探针未执行：场景 state.json 由 heredoc 嵌 $T1 生成，展开后 content 值携带字面单引号致 JSON 非法（char 150 处） |
| dsh-guard-scenario-batching | json_output final_content_is_second | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上，ws/test_scenarios.json 未被写出： |
| dsh-guard-scenario-batching | json_output other_path_allowed | test-defect | 测试用例自身缺陷（非产品缺陷） | 同上，other.txt 写探针未执行： |
| dsh-model-config-missing-model-fails | json_output explicit_error | test-defect | 测试用例自身缺陷（非产品缺陷） | stderr: dsh-app-boot lib/index.js:3566 "must be a top-level YAML array"——场景 cordis.patch.yml 写成 insert: 顶层 mapping，dsh 要求顶层数组，patch 解析先于模型配置检查即失败；场景文件缺陷 |
