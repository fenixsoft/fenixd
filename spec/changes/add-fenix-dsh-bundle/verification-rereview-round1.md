# 验证打回第 1 轮：复核纪要与修复记录

> 任务书「验证修复（原地打回第 1 轮）」三步的产出存档：8.1 逐条复核失败有效性、
> 8.2 按结论修复、8.3 重跑验证。配套证据：`/root/fenixd/.fenix/verify-evidence/add-fenix-dsh-bundle/`。

## 一、8.1 复核结论：15 个失败场景逐条定性

上轮 verification-report.md 的「修复后应全绿」预测错误——孤立重跑实证：BUG-01（dist 缺失）
修复后，isolated-load 仍 StartupError「模型未显式配置」。失败是**多层缺陷叠加**，逐条复核定性：

| # | 场景 | 定性 | 根因 | 修复面 |
|---|------|------|------|--------|
| 1-11 | 11 个 boot 类（isolated-load / one-based-ids / update-event-projection / get-list-and-empty / invalid-inputs / guard-main-tree-write / guard-no-env-passthrough / guard-image-read / guard-scenario-batching / approval-headless / agents-md-system-prompt-load） | **场景缺陷**（第二层） | 场景未供模型 config——spec 要求模型显式配置（缺任一要素即 StartupError fail-fast），场景的 `cordis.patch.yml` 却写入 `[]` | 场景：注入 `- id: fenix-model-config` patch 覆盖条目（provider/baseURL/apiKeyEnv/model 四要素 + `api: anthropic-messages` 对齐 fake_llm 的纯 Anthropic SSE 线协议） |
| 12 | 上述 12 场景的 `file:$REPO/dsh-bundle` 装法（除 peer-version-mismatch） | **场景缺陷**（第三层） | file: 拷贝装两态皆坏：peers-only=peer 断链；带 dependencies=官方包 hoist 进 profile 根 → dsh 运行时双副本 → `TOOL_RUNTIME_SCHEDULER` symbol 身份分裂 → `reading 'prepare'` 崩溃 | 场景：`file:` → `link:`（realpath 解析回 bundle 自己的 node_modules，唯一健全形态）；产品回退 peers-only（移除 dependencies） |
| 13 | model-config-missing-model-fails | **场景缺陷** | fixture 从 src/index.ts 提取主模块名 `fenix-dsh-bundle` 作 PNAME，config 绑错插件致「等自己提供的服务」死锁而非预期的显式配置错误 | 场景：钉 `PNAME="fenix-dsh-bundle/modelConfig"` |
| 14 | task-tools-get-list-and-empty | **产品缺陷** | TaskList 空态返回纯中文「（当前会话暂无任务）」，断言要求 `[]`/`no task`/`empty` 机器可读标记 | 产品：空态文案改 `[]（当前会话暂无任务）` |
| 15 | approval-headless-unattended | **场景缺陷** | state.json 的 bash turn 缺 dsh bash 工具必填属性 `description`（`missing required property "description"`） | 场景：补 `"description": "write approval smoke marker"` |
| 附1 | agents-md-system-prompt-load | **产品缺口** | spec 要求「Bundle MUST 经 system-prompt 分区装载工作区 AGENTS.md」；bundle 仅依赖原生 `dsh-agent-instructions`（durable **user** 消息，不进请求 system 字段），`body.system` 捕获永远无 marker | 产品：新增 `src/agentsMd.ts` 注册 `fenix:agents-md` 分区（见下） |
| 附2 | bundle-vitest-suite | **环境缺陷** | pnpm 12.11.2 strict-dep-builds：依赖树被拦构建脚本未表态即硬错 `ERR_PNPM_IGNORED_BUILDS`（`--ignore-scripts` 回退无效；package.json `pnpm.*` 字段已不被读取） | 产品：bundle 目录 `pnpm-workspace.yaml` 声明 `strictDepBuilds: false` + `ignoredBuiltDependencies` 显式知情忽略 6 项 |

## 二、8.2 产品侧修复明细

1. **AGENTS.md system-prompt 分区**（附1，spec「AGENTS.md 约定载体」的落点）：
   - 新增 `src/agentsMd.ts`：`agentsMdSectionText(root)` 纯函数（无文件/空文件返回空串，
     `<system-reminder>` 包装与原生措辞一致）+ `registerAgentsMdSection(ctx)`
     （`ctx.inject(["systemPrompt"], …)` → `section({ name: "fenix:agents-md", order: FILE_REFERENCE, text: () => 现读 cwd })`）；
   - `src/index.ts`：`FenixBundleContext extends AgentsMdContext`，apply 接线；
   - 实证：假模型端点捕获 `body.system` 含 marker 与正文（软链 AGENTS.md → CLAUDE.md）；
   - 双通道并存：原生 user 消息通道照旧（服务 dsh 生态约定），分区服务 spec 的 system-prompt 契约。
2. **TaskList 空态机器可读标记**（#14）：`[]（当前会话暂无任务）`。
3. **pnpm 12 兼容**（附2）：`pnpm-workspace.yaml`（strictDepBuilds:false + ignoredBuiltDependencies 六项，
   语义依据：bundle 测试面不消费原生构建产物，esbuild 平台二进制走 optionalDependencies）。
4. 单测：`tests/agentsMd.test.ts` 新增 6 例（分区形态/缺文件/空文件/软链/接线/空贡献），
   `tests/modelConfig.test.ts` 装配面桩补 inject 断言；vitest 83/83 绿，`pnpm build` 绿。

## 三、8.3 重跑结果：20/20 场景断言全绿

本地等装置重跑（冻结场景命令原样提取，DSH_HOME 隔离 + 假模型端点）：

| 场景 | 断言 | 结果 |
|------|------|------|
| dsh-verify-infra-helpers | helper_written/syntax_ok | ✓ |
| dsh-bundle-isolated-load | 5 断言 | ✓ |
| dsh-bundle-peer-version-mismatch | explicit_version_error/tools_not_registered | ✓ |
| dsh-bundle-manifest-pinning | 7 断言 | ✓ |
| dsh-task-tools-one-based-ids | 3 断言 | ✓ |
| dsh-task-tools-update-event-projection | 6 断言 | ✓ |
| dsh-task-tools-get-list-and-empty | 5 断言 | ✓ |
| dsh-task-tools-invalid-inputs | 3 断言 | ✓ |
| dsh-guard-main-tree-write | 5 断言 | ✓ |
| dsh-guard-no-env-passthrough | 2 断言 | ✓ |
| dsh-guard-image-read | 2 断言 | ✓ |
| dsh-guard-scenario-batching | 4 断言 | ✓ |
| dsh-approval-headless-unattended | 4 断言 | ✓ |
| dsh-model-config-missing-model-fails | 2 断言 | ✓ |
| dsh-model-config-schema-docs | 3 断言 | ✓ |
| dsh-bundle-vitest-suite | install_ok/tests_passed | ✓ |
| dsh-agents-md-symlink | 4 断言 | ✓ |
| dsh-agents-md-system-prompt-load | 3 断言 | ✓ |
| dsh-probe-findings-complete | 8 断言 | ✓ |
| dsh-probe-stderr-error-codes | 3 断言 | ✓ |

场景文件外科手术均按 SOP：/tmp 副本修改 → YAML+JSON 双校验 → 备份（`*.pre-modelcfg-20261013.bak`、
`*.pre-approval-fix-20261013.bak`）→ 放置主树 `.fenix/verify-progress/add-fenix-dsh-bundle/test_scenarios.json`。
