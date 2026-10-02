# SPEC 手工晋升（drafted→ready 人工放行通道）
<!-- knowledge: capability=manual-spec-promotion rev=1
     sources=spec/archive/2026-09-14-add-draft-promotion-gate -->

为停留在 drafted 的 SPEC 提供与自动晋升同语义的人工放行入口：Dashboard 与 CLI 共用同一晋升函数。

## 规则

- 共享晋升函数供自动晋升链与全部人工通道（Dashboard API、CLI）共用，语义一致：软化不可满足声明（含 dispute 审计留痕）→ 晋升 lint（Deliverables 声明 lint + tasks.md 可解析性 lint）→ 违规则停留 drafted 并把违规明细写入 STATE `error`（与自动晋升 lint 失败同格式）→ 通过则 transition `drafted → ready`。
- 幂等防御：目标 SPEC 不存在或状态非 drafted 时拒绝并返回明确原因，STATE 不发生任何变更。
- Dashboard 通道：`POST /api/spec-promote?project=<name>&spec=<name>` 执行共享晋升函数；项目页 spec 列表仅 drafted 行提供「晋升 ready」操作入口（带确认）；lint 失败时向用户展示违规反馈（API 返回失败与违规摘要，STATE error 可见）；对不存在的 spec 返回 404。
- CLI 通道：`bin/fenix_cli.py promote <spec> [--project <path>]`（缺省 project 为当前目录），调用同一共享晋升函数；执行结果（成功/违规列表/拒绝原因）打印终端，失败以非零退出码表示。
- 晋升落盘后 daemon 感知并派发实现：经既有 STATE watcher 事件，或最迟由 full_scan recovery 的 `_recover_ready` 分支兜底，不引入新的跨进程请求文件类型。
- 晋升闸口（`gates.promote_mode`）只作用于 drafted→ready 晋升环节：manual 档下闸口关闭不影响已晋升为 ready 的 SPEC 的正常派发。

## 溯源

- 2026-09-14 2026-09-14-add-draft-promotion-gate（spec/archive/2026-09-14-add-draft-promotion-gate） — 新增人工放行通道：共享晋升函数与幂等防御、Dashboard API 与按钮、CLI promote 命令、晋升后 daemon 感知派发
