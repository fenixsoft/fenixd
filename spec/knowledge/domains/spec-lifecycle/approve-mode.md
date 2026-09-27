# 审批模式（done 后推送门控）
<!-- knowledge: capability=approve-mode rev=1
     sources=spec/archive/2026-09-02-add-fenix-config -->

控制 SPEC 到达 `done` 后的出仓方式：自动推送远端并标记 `pushed`，或停留等待人工审批。push 审批是框架唯一的人工门。

## 规则

- 配置键 `gates.approve_mode`（`.fenix/config.yaml`），枚举 `manual` / `auto`，缺省 `manual`；`ConfigLoader` 校验取值，非法值抛出指明合法取值的配置错误；`config.template.yaml` 同步该字段与说明。
- `manual`（或缺省）：SPEC 到达 `done` 后保持 `done` 等待人工经 `/fenix-approve` 审查并推送；daemon 不得自动 push，也不推进 `pushed`。
- `auto`：SPEC 推进到 `done` 后自动执行审批——解析推送分支（优先 `STATE.md` 的 `branch` 字段，否则 `{worktree.implement_branch_prefix}/{spec_name}`，缺省 `fenix/<spec_name>`），在项目根执行 `git push origin <branch>`；成功后状态推进 `pushed` 并记 PROJECT_LOG。
- auto 推送失败时保留 `done` 状态、`error` 记录推送失败原因，不静默通过，供人工 `/fenix-approve` 兜底。
- 同一 SPEC 不重复触发自动审批：已 `pushed` 的 SPEC 再次被扫描时不推送、不转换。
- Dashboard 配置页提供审批模式可视化编辑（写入 `gates.approve_mode`），保存后提示「重启 daemon 后生效」；配置页展示当前生效值，选中 auto 时明示会真实推送 git 分支到远端。

## 溯源

- 史前复原 — done 后按审批模式配置自动 push 并标记 pushed，或转人工 /fenix-approve 审批；push 审批是唯一人工门
- 2026-09-02 2026-09-02-add-fenix-config — 审批模式配置化：`gates.approve_mode` 枚举与校验、auto 自动推送链与失败兜底、Dashboard 可视化编辑与风险提示
