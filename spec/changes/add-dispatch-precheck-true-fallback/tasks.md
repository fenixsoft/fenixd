## Deliverables

```yaml
- path: dsh-bundle/src/modelConfig.ts
  kind: modify
- path: dsh-bundle/tests/modelConfig.test.ts
  kind: modify
- path: core/agent_runner/harness/dsh_adapter.py
  kind: modify
- path: core/agent_runner/harness/__init__.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/systemd_hosting.py
  kind: modify
- path: bin/migrate_to_systemd.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_harness_default_fallback.py
  kind: modify
- path: tests/test_dispatch_precheck.py
  kind: new
- path: tests/test_systemd_env_path_hygiene.py
  kind: new
```

## 1. dsh-bundle 侧真对称回落（D1）

- [ ] 1.1 `assertModelExplicit` 形态划界重构：`config.model` 整体缺席（undefined/键不存在）→ 不抛错，返回回落形态标记，插件跳过显式覆盖并 WARN 留痕（含「config.model 缺席，回落 dsh 默认档」语义）；`config.model` 为 null/空串/对象但要素缺失 → 保持现行「模型未显式配置」fail-fast（笔误防护）
- [ ] 1.2 回落形态下 `agentDefaultModel`/`fenixModelConfig` 服务由 dsh 自身默认模型解析链（dsh-base 通道）供数，`headless-runner`（required）正常激活——以插件服务注册/降级逻辑实现，隔离 dsh-base 依赖（mock 注入）
- [ ] 1.3 vitest 单测（dsh-bundle/tests/modelConfig.test.ts）：无 patch 启动不抛 StartupError 且服务可用、部分 config.model（null/空串/缺要素对象）仍 fail-fast、显式全链校验路径行为与重构前一致（回归红线用例）
- [ ] 1.4 `pnpm build` 重建 dist + dsh-bundle 全量 vitest 绿（worktree 内 `pnpm install` 后执行）

## 2. 派发前置自检与失败归因（D2）

- [ ] 2.1 runner 派发前置自检：spawn 前按 `agent.harness` 选型 `shutil.which` 探测 harness binary（claude→`claude`、dsh→`dsh`），不可达短路该次派发（不产生 spawn 进程），失败证据带 `[harness-cli-unavailable]` 标记（复用既有归因标记管道）+ 修复指引文案（可执行名、当前 PATH 摘要、「检查 PATH / systemd EnvironmentFile」）；可执行名解析单源放 `core/agent_runner/harness/__init__.py`（VALID_HARNESS_VALUES 同源），`DshAdapter.check_health` 既有「未装」路径接入同一 `[harness-cli-unavailable]` 归因避免双口径
- [ ] 2.2 daemon 启动序列自检：启动时探测一次，不可达发单条 actionable 告警（进程内去重，不阻塞其余职能）；可达时不播报
- [ ] 2.3 升级信号豁免：`[harness-cli-unavailable]` 归因失败不计入 instant-fail-storm / repeated-failures 计数（与 `[model-chain-unavailable]` 不自动重派同款豁免面）
- [ ] 2.4 PATH 自愈：启动自检发现 `<home>/.local/bin/<harness>` 存在而 PATH 缺该目录且 `.fenix/systemd.env` 在场 → PATH 行幂等追加缺失目录（原子写 tmp+rename）+ 落 `restart_request`（JSON：reason/origin/date）+ 日志留痕；全常见目录未找到 binary 时不写 env 仅告警
- [ ] 2.5 pytest 单测（tests/test_dispatch_precheck.py）：自检短路 + 归因标记断言、可达放行零噪音、启动告警去重、豁免面不计数、自愈幂等追加 + restart_request 落位、binary 缺失不盲写

## 3. systemd env PATH 卫生（D3/D4）

- [ ] 3.1 `capture_env_candidate` 基线并集：基线目录集模块常量（`~/.local/bin`、`/usr/local/bin`、`/usr/local/sbin`、`/usr/sbin`、`/usr/bin`、`/sbin`、`/bin`），捕获源 PATH 缺失基线目录按序追加尾部，候选稿头部注释留痕「已追加目录清单与原因」；完整 PATH 产物逐字节不变；基线目录集比较与写入一律用展开后的绝对路径（`Path.expanduser`——env 文件值不做 `~` 展开，`~/.local/bin` 仅为文档记法）
- [ ] 3.2 `render_project_unit` 保底 PATH：unit 模板加 `Environment=PATH=<基线目录集>` 行（env 文件缺席时兜底；在场时被覆盖，systemd 语义注释说明）；PATH 值渲染时展开为绝对路径（systemd 不展开 `~`，字面 `~` 目录项会使保底 PATH 静默失效）
- [ ] 3.3 迁移摘要：`migrate_to_systemd.py` env 捕获段 plan 追加一行 PATH 卫生结论（「完整」或「补齐 <目录清单>」）
- [ ] 3.4 pytest 单测（tests/test_systemd_env_path_hygiene.py）：最小 PATH 补齐 + 留痕断言、完整 PATH 逐字节不变、unit 模板含保底行、迁移摘要结论行

## 4. 对称回落回归与端到端冒烟

- [ ] 4.1 既有回落测试更新（tests/test_harness_default_fallback.py）：无分配 spawn 用例补 bundle 侧联动断言（无 patch → 存活）；显式链字节级回归用例保持绿
- [ ] 4.2 端到端冒烟（DSH_HOME 隔离环境）：无 `agents.models` 分配 + harness=dsh + fenix profile 无 patch 启动 → dsh 进程存活、headless-runner 激活、执行一次最小任务完成；显式链（patch 三要素齐全）spawn 产物与基线一致
- [ ] 4.3 全量回归：fenixd pytest 既有套件 + dsh-bundle vitest 全量绿；`restart_request` 预演（全新进程消费 + 核心 API import）验证自愈信号链完整
