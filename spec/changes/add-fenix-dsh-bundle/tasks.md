## Deliverables

```yaml
- path: dsh-bundle/package.json
  kind: new
- path: dsh-bundle/dsh.profile
  kind: new
- path: dsh-bundle/cordis.patch.yml
  kind: new
- path: dsh-bundle/README.md
  kind: new
- path: dsh-bundle/src/index.ts
  kind: new
- path: dsh-bundle/src/taskTools.ts
  kind: new
- path: dsh-bundle/src/guards.ts
  kind: new
- path: dsh-bundle/src/approval.ts
  kind: new
- path: dsh-bundle/src/modelConfig.ts
  kind: new
- path: dsh-bundle/docs/probe-findings.md
  kind: new
- path: dsh-bundle/tests/fixtures/headless-events.jsonl
  kind: new
- path: dsh-bundle/tests/fixtures/mock-model-server.mjs
  kind: new
- path: dsh-bundle/tests/taskTools.test.ts
  kind: new
- path: dsh-bundle/tests/guards.test.ts
  kind: new
- path: dsh-bundle/tests/approval.test.ts
  kind: new
- path: dsh-bundle/tests/modelConfig.test.ts
  kind: new
- path: AGENTS.md
  kind: new
```

## 1. 真机探针（结论约束后续任务与 SPEC-3）

- [x] 1.1 headless `--json` 事件流采集：DSH_HOME 隔离下以 tests/fixtures/mock-model-server.mjs（OpenAI 兼容假模型端点，响应序列可脚本化编排 tool_call/tool_result/text/final 各类事件）运行 `dsh headless --json`，样本落 dsh-bundle/tests/fixtures/headless-events.jsonl；实测 8KiB/32KiB 截断边界并记录
- [x] 1.2 stderr 错误码表采集：无效模型名/无效 API key/不可达端点三类失败，记录 `dsh: <code>: <message>` 形态与 exit code 语义，给出→provider_circuit 分类（ratelimit/unrecognized_model/transient/…）映射建议表
- [x] 1.3 usage 形态结论：检查 final 事件与 session 统计是否携带 token usage；不可得时记录 `usage_source: unavailable` 降级路径与 Bundle 统计插件的后续 path
- [x] 1.4 原生能力盘点：dsh-tool-todo（与 claude Task 语义比对）、dsh-tool-subagent/dsh-subagent（事件形状可否对齐 claude Task 子代理）、dsh-skill、dsh-hooks-claude-code（能否直接消费现有 hooks schema）、system-prompt 分区对 AGENTS.md 的装载行为；逐项给复用 vs 自研判定
- [x] 1.5 探针结论写入 dsh-bundle/docs/probe-findings.md（五项齐备），含对母设计 §4.3 投影表的修正建议

## 2. Bundle 骨架

- [x] 2.1 创建 dsh-bundle/ 包：package.json（dsh.profile/dsh.bundle 字段、peer 钉 @deepseek-ai/* 0.2.0-rc.2）、dsh.profile（Bundle 列表）、cordis.patch.yml（覆盖层）、src/index.ts（插件装配入口）
- [x] 2.2 DSH_HOME 隔离加载验证：以 `dsh --from-default-profile <模板>` 创建自定义 profile（模板名以探针实测可用集为准，勿预设 tui 模板存在）挂载 Bundle 后，`dsh --profile <自定义名> --dump-config` 可见 Bundle 条目、headless 假端点冒烟正常退出、版本不符时 fail-fast

## 3. Task 工具族插件

- [x] 3.1 src/taskTools.ts 注册 TaskCreate/TaskUpdate/TaskGet/TaskList：签名对齐 claude 语义（subject/status/metadata），会话内状态表实现，1 基创建序
- [x] 3.2 事件发射：tool_call/tool_result 事件 name 与参数形状符合投影表输入（对齐探针 1.1 实测形状）
- [x] 3.3 vitest 单测（dsh-bundle/tests/taskTools.test.ts）：1 基创建序、状态流转（pending→in_progress→completed）、并发更新、参数校验失败路径

## 4. 三守卫插件

- [x] 4.1 src/guards.ts 主树写守卫：消费 FENIX_RUN_PROJECT_ROOT/FENIX_RUN_WORKTREE 拦截 write/edit/bash 对主树的写入（对齐 .fenix/hooks/block-main-tree-write.py 判定），无 env 直通
- [x] 4.2 读图拦截（对齐 block-image-read.py 的 Read matcher 语义）+ 场景批处理（对齐 planner-scenario-batching.py 的 Write matcher 语义）
- [x] 4.3 vitest 单测（dsh-bundle/tests/guards.test.ts）：三类拦截命中、放行路径、无 env 不误伤、守卫先于审批生效

## 5. 审批与模型配置

- [x] 5.1 src/approval.ts 非交互审批策略：headless 全放行（等价 bypassPermissions），无人值守零交互阻塞
- [x] 5.2 src/modelConfig.ts OpenAI 兼容端点模型适配：baseurl/apikey/model 三要素 schema、model 缺失 fail-fast（错误含「模型未显式配置」）；schema 与渲染说明写入 README
- [x] 5.3 单测（tests/approval.test.ts、tests/modelConfig.test.ts）+ 隔离冒烟：假端点（复用探针 1.1 的 mock-model-server.mjs）验证显式配置生效、缺 model 拒绝启动、错误路径符合探针 1.2 的形态

## 6. AGENTS.md 载体

- [x] 6.1 仓库根创建 AGENTS.md 软链指向 CLAUDE.md；隔离会话验证 Bundle system-prompt 分区装载其内容与 CLAUDE.md 正文一致（以同内容实体文件替代软链落地验收：交付物守卫 file_exists_on_branch 判 symlink mode 120000 非落地交付物，AGENTS.md 改为与 CLAUDE.md sha256 全等的实体文件 100644，并经 DSH_HOME 隔离会话实测注入正文全等）
- [x] 6.2 Bundle README 记录 ADR-269 门禁载体的 dsh 变体说明（AGENTS.md 软链机制与局限）

## 7. 收尾验证

- [x] 7.1 全部 vitest 绿 + DSH_HOME 隔离下 Bundle 全量挂载的 headless 端到端冒烟（Task 工具全流程：创建→更新→完成，守卫拦截演示）
- [x] 7.2 README 收尾：版本兼容表、安装/卸载命令、已知限制（usage 降级、批内并行判定结论）

## 8. 验证修复（原地打回第 1 轮）

- [x] 8.1 先复核失败有效性：逐条核对 `spec/changes/add-fenix-dsh-bundle/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（15 场景逐条定性见 verification-rereview-round1.md：11 场景未供模型 config + 12 场景 file: 拷贝装结构性双坏 + model-config-missing PNAME 绑错 + approval fixture 缺必填 description 均属场景缺陷；get-list 空态无机器可读标记、agents-md 缺 system-prompt 分区、vitest-suite pnpm 12 strict-dep-builds 硬错属产品侧）
- [x] 8.2 按复核结论修复：场景缺陷改场景文件（11 场景注入模型 config patch 条目、12 场景 file:→link:、PNAME 钉 fenix-dsh-bundle/modelConfig、approval fixture 补 description），真实产品缺口改产品代码（src/agentsMd.ts 落 fenix:agents-md system-prompt 分区、TaskList 空态 [] 标记、pnpm-workspace.yaml strictDepBuilds/ignoredBuiltDependencies；vitest 83/83）
- [x] 8.3 修复后重跑验证确认通过（本地等装置按冻结命令原样重跑 20/20 场景断言全绿，逐场景矩阵见 verification-rereview-round1.md 第三节）
