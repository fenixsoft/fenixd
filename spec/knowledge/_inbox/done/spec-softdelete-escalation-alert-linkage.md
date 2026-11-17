# SPEC 软删除通道与 spec-review-rejected 升级告警不联动（排查候选）

## 背景

2026-11-17 人工在 Dashboard 运维页对告警「方案评审被否决 evo-fix-self-review-window-gap · fenixd」（alert `8c715662226d`，signal_type=`spec-review-rejected`，2026-11-16 22:42 +08 发射）执行注册选项 abandon（丢弃），前端 toast「裁决执行失败，告警保持未处理，可调整后重试」，告警保持 pending。排查失败原因。

## 结论（当前事实）

- SPEC 管理的软删除通道不联动关闭裁决类升级告警：spec 删除端点（`core/dashboard/routes/spec_routes.py` ~948 行，直接调 `dashboard_data.soft_delete_spec`）与裁决 abandon 执行器（`core/dashboard/data/admin_actions.py:2320` `_exec_abandon`）共用底层 `core/dashboard/data/spec_archive.py:136` `soft_delete_spec`，但删除侧不写任何告警闭合记录。spec-review-rejected 告警仅被「告警上执行裁决成功→mark handled」、老化升级、验证翻绿联动等路径闭合；spec 先经别通道删除后，告警与 spec 真实状态脱钩，其推荐动作（abandon）变得永不可执行。
- 对已软删除的 spec 再执行 abandon 必然失败：`soft_delete_spec` 对「活跃 STATE.md 与归档清单 `.fenix/STATE.archive.md` 均不含该 spec」幂等返回 `{found: False}`（docstring D6：不发任何文件操作），`_exec_abandon` 把 `found=False` 转为失败 `error="spec not found: <spec>"`；alert-resolve 端点（`core/dashboard/routes/alert_routes.py` ~655）400 `{error}（告警保持未处理，可调整后重试）`，前端 toast 统一文案（`core/dashboard/static/src/hooks/useAlertAdjudication.tsx:101`），详细原因仅在告警卡片内联回显。是否应把「目标态已达成（spec 已不在）」判为幂等成功是待立项的产品决策，现状按失败保留告警。
- 两条归档通道的目录命名可作通道判别指纹：`soft_delete_spec` → `spec/archive/<name>-<Unix秒>/`（无日期前缀，且不写归档清单）；`archive_spec`（`spec_archive.py:500`，管理页归档/daemon 自动归档链）→ `spec/archive/YYYY-MM-DD-<name>/`，归档成功即把 STATE 条目迁出至清单 `.fenix/STATE.archive.md`（`state_evicted`/降级 `evict_warning`）。
- 人工 alert-resolve 失败路径零落痕：`execute_adjudication_choice`（`admin_actions.py:3147`）docstring 明示「只执行动作，不做 handled 标记与 disposition 留痕——由调用方按各自通道收口」；端点失败分支只回 400，不写 disposition、不给 ESCALATION 告警打 `result=failed` 戳、不落 journal（无异常）。留痕型失败回执（`mark_signal_handled(handled=False, action_taken, result)`，`core/admin_store.py:1161`，只匹配 kind=SIGNAL）是 Admin 链通道专用。人工路径失败的唯一痕迹是 400 响应体，事后排查只能文件态比对。
- 存量收口路径：对「spec 已不存在」的裁决告警用「标记已处理」（`POST /api/alerts/<id>/handled?project=<name>`）人工收口，勿再执行 abandon。

## 证据

- 告警记录：`/root/fenixd/.fenix/admin_alerts.json` alert `8c715662226d`（choices=[revise_reproposal, force_advance, abandon]，handled=False）；全库仅 2 条 aging disposition（2026-11-16 16:43/20:43 UTC，actor=aging-watch），无人工裁决 disposition；归档 JSONL（`admin_alerts_archive.jsonl`）0 条相关记录。
- spec 已于 2026-11-16 23:15:56 +08 软删除：目录 `spec/archive/evo-fix-self-review-window-gap-1794842156/`（Unix 秒命名=soft_delete_spec 指纹）；自动提交 `3e18548f3`「[fenix] archive: add-distill-run-work-summary、evo-fix-self-review-window-gap 归档入库」（23:18:03 +08）——同 commit 内 add-distill-run-work-summary 为日期前缀目录（archive_spec 通道），证明当晚两通道各执行一次。
- 文件态比对（2026-11-17）：`parse_state('/root/fenixd')` 50 spec 不含目标；`parse_archived_state`（`.fenix/STATE.archive.md`，543 条）不含目标 → `found=False` 必然。
- `fenix-dashboard.service` journal（2026-11-16 23:10–23:19、2026-11-17 08:40–09:25）无任何 alert-resolve 异常行，排除「昨夜 abandon 成功但 handled 写入失败」形态（该形态必留 `logger.exception("alert-resolve handled 标记写入异常 alert=…")`）。
