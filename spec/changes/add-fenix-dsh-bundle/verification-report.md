# 验证报告：add-fenix-dsh-bundle

> ⚠️ 本报告由框架于 2026-10-13T09:42:15Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-13T09:42:14.827518+00:00+run-result@mtime1791884534902250958

## 结论：✅ 通过（verified）

**状态：verified — 20/20 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 20/20 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 20 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 11.43M |
| 本链增量 Token（输出） | 0.17M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dsh-verify-infra-helpers | 验证基础设施：落盘共享假模型端点脚本（Anthropic Messages SSE 流式、脚本化 turns、system prompt 捕获），供后续 dsh 驱动类场景复用。出处：本机探针实测 dsh 0.2.0-rc.2 headless 契约（DEEPSEEK_BASE_URL env 路由 + SSE 流式响应）。 | pass | 0/4 | - |
| dsh-bundle-manifest-pinning | Bundle 骨架静态契约：package.json 声明 dsh.bundle（patch 指向覆盖层）、dsh.profile 文件存在且列出 Bundle、cordis.patch.yml 为可解析覆盖层、peerDependencies 全部钉 0.2.0-rc.2、运行依赖仅官方 @deepseek-ai/* 包、README 含版本兼容说明与安装/卸载命令、src/index.ts 装配入口存在。出处：spec.md「Bundle 骨架与版本钉扎」+ tasks.md 2.1 交付物清单。 | pass | 0/8 | - |
| dsh-model-config-schema-docs | 模型配置静态契约：src/modelConfig.ts 实现含「模型未显式配置」错误文案与 baseurl/apikey/model 三要素 schema；README 载明配置 schema（供 SPEC-3 provider 链渲染）。出处：spec.md「模型显式配置契约」+ tasks.md 5.2。 | pass | 0/4 | - |
| dsh-bundle-vitest-suite | Bundle 自带 vitest 单测全绿：dsh-bundle 内 pnpm install 后运行 vitest 套件退出码 0（覆盖 tasks 3.3 taskTools、4.3 guards、5.3 审批/模型配置单测的实现方自证）。环境依赖（npm registry 可达）有 fallback: pnpm 本地 store 缓存 prefer-offline。出处：tasks.md 3.3/4.3/5.3/7.1。 | pass | 0/3 | - |
| dsh-agents-md-symlink | AGENTS.md 约定载体静态契约：仓库根 AGENTS.md 为指向 CLAUDE.md 的软链（单一真相源），读取内容与 CLAUDE.md 完全一致。出处：spec.md「AGENTS.md 约定载体」+ design.md 决策 5。 | pass | 0/5 | - |
| dsh-probe-findings-complete | 真机探针结论沉淀齐备：dsh-bundle/docs/probe-findings.md 覆盖五项（headless --json 事件流样本、stderr 错误码→provider_circuit 分类映射、usage 形态结论含 usage_source/降级路径、原生能力盘点含 dsh-tool-todo/subagent/skill/hooks-claude-code 复用 vs 自研判定、母设计 §4.3 投影表修正建议）并记录 8KiB/32KiB 截断边界；tests/fixtures/headless-events.jsonl 为真实事件流且 session/text/tool_call/tool_result/final 各类型至少一例。出处：spec.md「真机探针结论沉淀」+ tasks.md 1.1-1.5。 | pass | 0/9 | - |
| dsh-bundle-isolated-load | DSH_HOME 隔离加载：隔离目录创建自定义 profile 挂载 dsh-bundle，--dump-config 可见 Bundle 条目，headless 假端点冒烟按契约退出（final 事件产出），TaskCreate 出现在会话工具表，真实 ~/.dsh 零写入。出处：spec.md「DSH_HOME 隔离加载」+ 本机探针 profile 形态实测。 | pass | 0/7 | - |
| dsh-bundle-peer-version-mismatch | peer 版本不符 fail-fast：复制 bundle 并把其 @deepseek-ai/* peer 范围改为 ^9.9.9 后挂载，加载以明确版本不兼容错误失败（stderr 明示 peerDependencies 对照），且 bundle 工具未注册（TaskCreate 调用得 unknown tool 错误）——不静默降级。出处：spec.md「peer 版本不符 fail-fast」+ dsh-app-boot README peer 运行时版本检查。 | pass | 0/3 | - |
| dsh-task-tools-one-based-ids | Task 工具族 1 基创建序：同一 headless 会话内假模型连续 TaskCreate 三条任务，tool_result 依次呈现 taskId 1、2、3（Task #1/#2/#3 created 语义）。出处：spec.md「1 基创建序」+ core/run_task_track.py:305 读侧硬约定。 | pass | 0/3 | - |
| dsh-task-tools-update-event-projection | 状态更新事件可投影：TaskCreate 后 TaskUpdate 置 completed，tool_call 事件 name=TaskUpdate、input 含整数 taskId=1 与 status=completed，字段名与 claude tool_use block 语义对齐（可被母设计 §4.3 投影表直接消费）。出处：spec.md「状态更新事件可投影」+ docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md §4.3。 | pass | 0/6 | - |
| dsh-task-tools-get-list-and-empty | TaskGet/TaskList 可用与空状态：创建前 TaskList 返回空列表（完成状态、非错误——空状态覆盖）；TaskCreate 后 TaskGet(1) 返回所建任务 subject；TaskList 包含该任务。出处：spec.md Task 工具族等价 + 场景覆盖规则空状态条目。 | pass | 0/6 | - |
| dsh-task-tools-invalid-inputs | Task 工具参数校验失败路径：TaskUpdate 不存在的 taskId=99 返回工具错误结果；TaskCreate 空 input（缺 subject）被参数校验拒绝。出处：tasks.md 3.3 参数校验失败路径 + spec.md Task 工具族等价。 | pass | 0/3 | - |
| dsh-guard-main-tree-write | 主树写守卫：设置 FENIX_RUN_PROJECT_ROOT/FENIX_RUN_WORKTREE 后，headless 会话（全放行审批）写主树文件被阻断且错误含主树只读语义、主树磁盘无落盘（守卫先于审批生效）；写 worktree 内路径放行；写主树 .fenix/verify-progress 白名单路径放行。出处：spec.md「主树写入被拦截」+ .fenix/hooks/block-main-tree-write.py 判定语义。 | pass | 0/6 | - |
| dsh-guard-no-env-passthrough | 无 env 守卫不误伤：未设置两个 FENIX_RUN_* env 时，对同样主树路径的写入直接放行落盘（等价 block-main-tree-write.py 无 env 直通行为）。出处：spec.md「无 env 时守卫不误伤」。 | pass | 0/3 | - |
| dsh-guard-image-read | 读图拦截：headless 会话 read 文本文件放行；read .png 图片目标被阻断且错误含「不支持图像输入」语义（对齐 block-image-read.py 的 Read matcher 语义）。出处：spec.md 三守卫等价 + .fenix/hooks/block-image-read.py。 | pass | 0/3 | - |
| dsh-guard-scenario-batching | 场景批处理守卫：首次 Write 带肉（非空 steps）的 test_scenarios.json 被阻断；文件已存在后的重写放行；写非场景路径放行（对齐 planner-scenario-batching.py 的 Write matcher 语义）。出处：spec.md 三守卫等价 + .fenix/hooks/planner-scenario-batching.py。 | pass | 0/5 | - |
| dsh-approval-headless-unattended | 非交互审批全放行：headless 会话执行守卫放行路径的 bash 工具调用直接执行（无交互确认等待），产物落盘、final 事件产出、进程按契约退出——等价 bypassPermissions 无人值守零阻塞。出处：spec.md「无人值守不阻塞」。 | pass | 0/5 | - |
| dsh-model-config-missing-model-fails | 模型显式配置契约：patch 配置提供 baseurl/apikey 而缺 model 时，会话创建以「模型未显式配置」错误失败；本场景不设 DEEPSEEK_* env，若回退 dsh 默认档即视为违约。出处：spec.md「缺 model 配置即拒绝启动」+ design.md 决策 4（narrative 网关别名事故承袭）。 | pass | 0/3 | - |
| dsh-agents-md-system-prompt-load | system-prompt 分区装载一致：含 marker 文本的工作区 CLAUDE.md（经 AGENTS.md 软链）在挂载 Bundle 的 headless 会话中进入 LLM 请求 system prompt（假端点捕获请求体验证 marker 与正文均在）——与 claude 通道注入等价；本机探针实证 dsh 原生不含工作区 CLAUDE.md，marker 出现即 Bundle 分区生效。出处：spec.md「装载内容一致」。 | pass | 0/4 | - |
| dsh-probe-stderr-error-codes | stderr 错误码形态真机取证：不可达模型端点（127.0.0.1 死端口）下 headless 运行以非零退出失败，stderr 呈 dsh: <CODE>: <message> 形态，样本留存供 probe-findings 错误码表对账。出处：tasks.md 1.2 + spec.md 探针要求；形态来自本机探针实测（dsh: STREAM_CLOSED: ...，exit 1）。 | pass | 0/5 | - |
