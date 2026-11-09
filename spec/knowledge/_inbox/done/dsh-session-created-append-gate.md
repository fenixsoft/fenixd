# dsh session/created 同步派发期会话流只读（append 闸）——标题类插件必须推迟落盘

## 背景

`add-dsh-session-title-archive` 落地后，fenixd spawn 的 dsh 会话在 web 列表仍未显示确定性标题（`<工程> · <worktree>`），且全程无 WARN/错误痕迹。装配面（cordis.patch.yml entry、dump-config 有效配置、dist 构建、profile 软链）逐项核实均完好，最终用同款接线的 `--patch` 探针在隔离 DSH_HOME 端到端复现定位根因。

## 结论（当前事实）

- dsh-session 的 `announce()` 在**同步派发** `session/created` 监听器期间把会话置 `announcement="dispatching"`，此时会话流**只读**：任何 append（含 `sessionTitle.rename()` 内部的 `session/title` 记录追加）必抛 `session "<id>" cannot append before session/created completes`；派发循环同步结束后才置 `"complete"` 解禁（dsh-session 源码注释："The Session remains read-only throughout synchronous dispatch; successful completion enables appends"）。
- 因此 `session/created` 监听器内**禁止同步写会话流**；需要落盘的插件（标题、首条消息加工等）必须经 `queueMicrotask`（或等价调度）推迟到派发完成后执行。微任务仍先于 headless `run()` 续行与首条消息兜底，`source=user` pin 语义不受影响。
- headless 启动序不存在激活竞态：`dsh-headless run()` 首行 `await ctx.get("loader")?.await()` 等待插件激活完成后才 `agents.create`→`announce`，监听器注册必然早于事件。
- 插件内 try/catch + `logger.warn` 的失败安全模式在 headless 车道是**静默**的（无落盘、stderr 不入日志），吞错缺陷不会留下可见痕迹——headless 插件的行为验证只能端到端（真 spawn + 解剖 `sessions/<dir>/session.v4.jsonl.zstd` 流，`/usr/bin/zstd -dc` 解压）。
- session/title 记录形态（v4 流）：`{"type":"session/title","seq":0,"data":{"title":"…","messageSeqs":[],"source":{"kind":"user"}}}`；`kind=user` 即 pin 态，抑制 dsh-base 的 `session-title-llm` LLM 兜底调度（流中不再出现 `title-llm-request`）。
- dsh 会话目录名仅由 cwd 派生（`--root-fenixd--` 形态），与标题无关；标题只看 spawn env `FENIX_RUN_PROJECT_ROOT` / `FENIX_RUN_WORKTREE`。

## 证据

- 探针复现（隔离 `DSH_HOME` + `--patch` 覆盖层，同款 inject/on/rename 接线）：`[probe] rename 失败: session "…" cannot append before session/created completes`——装配完好下 rename 确定性必败，非竞态。
- 修复后端到端复验（2026-11-09 10:49，真实 fenix profile）：`session/created` 后 7ms、seq 0 落 `session/title` `source.kind=user`、`title="fake-proj · fake-wt"`，流中零 `title-llm-request`。
- 源码：`dsh-session/lib/index.js` `announce()` 派发循环 + announcement 旗标；`dsh-headless/lib/index.js` `run()` 启动序；`dsh-session-title/lib/index.js:219` 服务名 `"sessionTitle"`。
- 修复提交：fenixd 仓库 `0d5f066db`（`dsh-bundle/src/session-title.ts` queueMicrotask 化 + `tests/session-title.test.ts` 新增 append 闸契约用例，vitest 128 passed）。
