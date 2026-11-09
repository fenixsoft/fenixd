# Tasks: add-dsh-session-title-archive

## Deliverables

```yaml
- path: dsh-bundle/src/session-title.ts
  kind: new
- path: dsh-bundle/src/session-tidy-helper.ts
  kind: new
- path: dsh-bundle/cordis.patch.yml
  kind: modify
- path: dsh-bundle/README.md
  kind: modify
- path: dsh-bundle/tests/session-title.test.ts
  kind: new
- path: dsh-bundle/tests/session-tidy-helper.test.ts
  kind: new
- path: core/dsh_session_tidy.py
  kind: new
- path: core/config.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_dsh_session_tidy.py
  kind: new
- path: dsh-bundle/dist/session-tidy-helper.mjs
  kind: reference
- path: .fenix/config.yaml
  kind: reference
```

## 1. dsh-bundle 标题装配（bundle 侧）

- [ ] 1.1 新增 `dsh-bundle/src/session-title.ts`：标题插件——从 spawn env `FENIX_RUN_PROJECT_ROOT` / `FENIX_RUN_WORKTREE` 派生确定性标题（格式 `<工程basename> · <worktreebasename>`，UTF-8 字节截断至 `maxTitleBytes=120`），经 `ctx.sessionTitle` 命名入口落会话 header（优先 `rename()` 语义；若安装版 SDK typings 表明 provider 接口更贴合则以 provider 实现，实现期二选一并留注释）；env 缺失逐级回退、全缺不命名不抛错；幂等（已有非默认标题不覆盖）。vitest 单测覆盖：正常派生 / 超限截断 / 单 key 回退 / 双缺不抛错 / 幂等（`dsh-bundle/tests/session-title.test.ts`）。
- [ ] 1.2 `dsh-bundle/cordis.patch.yml` 追加 `@deepseek-ai/dsh-session` 与 `@deepseek-ai/dsh-session-title` 服务条目（limits 全显式：`fallbackMaxWords: 8` / `fallbackMaxBytes: 96` / `maxTitleBytes: 120`）与 1.1 插件 entry；遵守既有装配纪律（服务为 `- id:` config 段形态、MUST NOT 写进任何 entry 的 inject 列表；title 服务依赖 session store 的装配顺序以 cordis.patch.yml 头注既有事故教训为准）；`pnpm build` 与全量 vitest 通过。
- [ ] 1.3 组装冒烟：临时 `DSH_HOME`（worktree 内目录）+ `plugin add link:<repo>/dsh-bundle` + `dsh --profile <临时profile> --dump-config` 断言新增服务条目出现（复用 `core/agent_runner/harness/dsh_adapter.py` 健康检查同款探测形态）；冒烟脚本入 `dsh-bundle/tests/`（可执行脚本或 vitest 集成用例，二进制缺席时明确 skip 并留痕）。

## 2. dsh-bundle 归档 helper（bundle 侧）

- [ ] 2.2 新增 `dsh-bundle/src/session-tidy-helper.ts`：CLI（`--url <web基址> --secret-file <dsh_home>/.credentials.yaml --session-id <id> --timeout <秒>`），经 `@deepseek-ai/dsh-api-gateway/client` 开 `/api/remote.mux` 连接调用 `ctx.remote.workspace.archiveSession(sessionId)`；退出码三分类（0=成功/已归档幂等、2=可重试〔连接失败/超时/session-active〕、1=致命〔凭据缺失/协议错〕），stdout 单行 JSON（`{ok, session_id, outcome, detail}`）；编译产物入口为 `dsh-bundle/dist/session-tidy-helper.mjs`（`pnpm build` 增加该 entry，产物 gitignored 不入库）。
- [ ] 2.1 鉴权打通探针：以本机真实 web（`/root/.dsh/.credentials.yaml` 的 `records.client-connection.browser-session.payload.secret`）核实握手精确形态（header/cookie/upgrade 参数名，以 `@deepseek-ai/dsh-api-gateway/client` SDK 源码为准），将结论与最小连通性证据写入 `dsh-bundle/docs/probe-findings.md` 新章节；探针脚本入 `dsh-bundle/tests/`（无真实 web 时明确 skip 留痕）。若 grant 形态无法接入，按 design.md 风险段降级（credential seam 读取）并在 `.fenix-run-result.json` 申报实现路径变更。
- [ ] 2.3 helper 测试 `dsh-bundle/tests/session-tidy-helper.test.ts`：参数解析/退出码映射/JSON 输出契约单测 + 归档调用集成用例（以临时 `DSH_HOME` 启动隔离 dsh web 实例验证 `archivedSessionIds` 写入与「已归档」幂等分类；若 dsh 无独立 web 启动入口，则以最小 WS stub 复现 gateway invoke 帧并在用例注释注明差异）。

## 3. daemon 侧 tidy 投递（core 侧）

- [ ] 3.1 新增 `core/dsh_session_tidy.py`：投递器——同步子进程调用 helper（超时缺省 10s）→ 失败入持久化重试队列（JSONL，`<state_dir>/dsh_session_tidy/pending.jsonl`，daemon 重启恢复消费）；backoff 重试、放弃阈值（缺省 200 条或 30 天，先到为准）放弃时 WARN；「已归档」按成功；队列并发 1。单测：入队/重试/放弃/幂等分类/重启恢复（队列文件读写 round-trip）。
- [ ] 3.2 `core/config.py` 新增 `agent.dsh_web_url`（缺省 `http://127.0.0.1:3080`，非法 URL 启动校验报错）与 `agent.dsh_session_tidy`（缺省 true；false 时投递暂停、队列不清空）；分层覆盖与热重载语义对齐 `agent.harness` 同面（`get_harness` 邻域既有模式）；校验与缺省单测并入 `tests/test_dsh_session_tidy.py`。
- [ ] 3.3 `core/agent_runner/runner.py` 终态收尾挂接：`agent.harness: dsh` 且开关开启且终态已捕获 `session_id`（`dsh_adapter` 投影）时调用 3.1 投递器；整段 try/except 包裹——任何异常 WARN 留痕且 MUST NOT 影响 run 终态指标行、门禁与 run 主链路；`agent.dsh_home` 缺省解析复用既有配置面。单测（monkeypatch helper 调用）：成功/超时/异常三形态均不影响终态指标；非 dsh harness 零动作。

## 4. 文档

- [ ] 4.1 `dsh-bundle/README.md` 增补：标题装配说明（服务条目与 limits）、session-tidy-helper 用法与退出码表、部署注意（web 需在线以实时归档，离线由 daemon 队列兜底；`.credentials.yaml` 依赖）；明确「分组归工程工作区受 dsh-workspace cwd 精确匹配 + 无 move API 限制，不在本 bundle 范围」。
