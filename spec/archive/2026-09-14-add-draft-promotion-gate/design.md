# add-draft-promotion-gate — 设计

## Context

当前 drafted → ready 晋升的唯一闸口是 `PMEngine._on_spec_drafted`（core/pm_engine/engine.py:170），内部依次执行：

1. 晋升前软化（`soften_unsatisfiable_declarations`，dispute 审计留痕 `promotion-soften`）
2. 晋升 lint（`_lint_deliverable_declarations` + `_lint_tasks_parseable`，违规保持 drafted 并写 STATE error）
3. `transition(spec, "ready")` + 直调 `_on_spec_ready` 排队实现

触发路径有四条，全部汇聚到该方法：`spec_drafted` 事件、`start_after` 到期唤起（engine.py:496）、full_scan recovery re-trigger（event_bus.py:143 `handle_event("spec_drafted")`）、外部 drafted 写入。因此闸口放在 `_on_spec_drafted` 入口即可全覆盖，无需改动任何调用方。

人工放行的感知链路已存在：外部进程用 `StateMachine` 把 drafted transition 为 ready 落盘 STATE.md 后，daemon 侧 event_bus full_scan recovery 的 ready 分支（`_recover_ready`，event_bus.py:169）会在无存活子进程时清 error 并重新派发；STATE.md watcher 事件提供更即时的触发。无需新请求文件类型。

配置面既有模式：`gates.approve_mode` 的完整链路——`config.py` 校验（VALID_APPROVE_MODES）+ getter（`get_approve_mode` 缺省 manual）→ `data.py` 受管键白名单（gates.approve_mode）→ `ApprovalModePanel.tsx` → docs/help/08-config.md 配置表。新键完全复用该模式。配置热更新（30s mtime 原地重载）已落地，PMEngine 每次晋升时读 config 即可感知设置变化。

Dashboard spec 操作 API 既有先例：`_api_spec_freeze/unfreeze/start_after`（server.py:583-675）+ `data.py` 对应函数（直接以项目路径操作 STATE.md，含文件锁），晋升 API 照此模式新增。

CLI：`fenixd.py` 是 daemon 主程序（无 argparse，误执行会拉起 daemon），不是 CLI 工具；`bin/` 下有 `fenix_*` 命名习惯（fenix_spec.py、fenix_process.py 等）。CLI 入口须新建，不得挂到 fenixd.py。

## Goals / Non-Goals

**Goals:**
- 配置键 `gates.promote_mode`（枚举 auto/manual，缺省 auto）控制草稿晋升，默认行为零变化
- manual 下 drafted SPEC 全触发路径停留草稿态（无 error、无派发），等待人工放行
- 人工放行双通道：Dashboard 按钮 + CLI 命令，与自动晋升共享同一晋升语义（软化+lint+transition）
- 设置页审批页签单选（与 approve_mode 同构）位于其上方；docs 同步

**Non-Goals:**
- 不改变 ready 之后任何调度/审批行为（done 后 approve_mode 门控不受影响）
- 不实现 drafted 草稿的在线编辑/预览 UI（阅读草稿走现有 spec 详情/文档查看）
- 不为「晋升请求」新增跨进程请求文件类型（感知走既有 watcher + full_scan recovery）
- 不支持批量晋升或多选操作（单 spec 粒度即可）

## Decisions

### D1: 闸口放 `_on_spec_drafted` 入口（单点全覆盖）
检查 `ConfigLoader.get_promote_mode(self.config)` 于方法第一行：manual 时记 info 日志（含 spec 名与「等待人工放行」语义）后直接 return，不软化、不 lint、不写 error。

- 替代方案：在四个调用方各自分支判断——需要改 event_bus（跨模块）且未来新增触发路径易漏；单点闸口天然全覆盖（含未来路径）。
- 关闭时不写 error 的理由：error 会触发 UI 告警与重派重试语义，而「等待人工放行」是设计行为；写 error 会造成误报噪声与 recovery 误动作。

### D2: 晋升核心提取为共享函数（新模块 `core/pm_engine/promotion.py`）
把 `_on_spec_drafted` 中「软化（含 dispute 审计）+ lint + 违规写 error」的主体提取为
`promote_drafted(project_root, spec_name, *, state_machine, logger) -> dict`
（返回 `{"ok": bool, "violations": [...]}` 或拒绝原因），`_on_spec_drafted` 重构为：闸口检查 → 调用共享函数 → ok 则 `transition ready` + `_on_spec_ready`。CLI 与 dashboard_data 各自构造 `StateMachine`/`Logger` 后调用同一函数。

- 替代方案：CLI/dashboard 各自复制组合软化+lint 逻辑——lint 规则演进（如 add-declaration-premechanize 后续）会漂移，双实现曾在本仓库造成过治理事故（admin unpack 漏改类）。
- transition 放调用方而非共享函数内：PMEngine 通道 transition 后直调 `_on_spec_ready`（进程内即时排队），外部通道 transition 后依赖 watcher/full_scan 感知；共享函数保持「软化+lint+判定」纯语义，transition 收尾由调用方完成，避免共享函数内隐含派发行为。

### D3: 配置键命名与缺省 `gates.promote_mode = "auto"`
与 `gates.approve_mode` 同段同构（gates = 流程门控语义，值域一致 auto/manual），缺省 auto 保证零迁移、现行为不变；getter 命名对齐 `get_approve_mode` → `get_promote_mode`。校验对齐既有 `validate` 模式（非枚举值报错）。

### D4: Dashboard API `POST /api/spec-promote` + `data.py::promote_spec`
照 `_api_spec_unfreeze` 模式：路由分发、project/spec 校验（404）、调 `dashboard_data.promote_spec(Path(project["path"]), spec)`。`promote_spec` 内部构造 StateMachine/Logger 调共享晋升函数；非 drafted 拒绝（200 + ok:false + reason，对齐 freeze 对终态的处理先例）、lint 违规返回 ok:false + violations 且 error 已写 STATE。受管键白名单同步加 `gates.promote_mode`（读侧 sources 标注 + 写侧提取，data.py:3410/3613 两处）。

### D5: 设置 UI 与项目页按钮
`ApprovalModePanel.tsx` 顶部（approve_mode Form.Item 之前）加 `Form.Item name="promote_mode"` + `Radio.Group` 单选（manual/auto，与 approve_mode 单选同构；manual 上、auto 下），保存时并入 `gates` 载荷（`{gates: {promote_mode, approve_mode}}`——注意保留 approve_mode 原值避免整段覆盖丢失）。文案：「草稿晋升模式（gates.promote_mode）」+ 各选项说明「manual — 人工审批：SPEC 停留在草稿态供人工阅读，确认后经 /fenix-ready、项目页按钮或 CLI 手动放行」「auto — 自动晋升：SPEC 注册为草稿后立即自动晋升 ready 并进入调度」。

项目列表页 spec 操作区（pages/projects/list.tsx，现有 freezeSpec/unfreezeSpec 调用所在组件）为 `status === 'drafted'` 的行加「晋升 ready」按钮（Popconfirm 确认），失败时 message.error 展示 API 返回的违规摘要。`services/dashboard.ts` 加 `promoteSpec`。

### D6: CLI 入口 `bin/fenix_cli.py`
新建（`fenix_*` 命名习惯），argparse 子命令 `promote <spec> [--project <path>]`（缺省 cwd），调共享晋升函数，结果打印 + 退出码（成功 0 / 失败非 0）。后续人工操作类子命令（如 freeze）可在此累积，本期只做 promote。

### D7: docs 同步
`docs/help/08-config.md` gates 配置表加 `promote_mode` 行（缺省/取值/热更新列，对齐 approve_mode 行格式）；`docs/help/06-governance.md` 增补「草稿人工放行」小节（单选位置、三种放行方式、lint 拦截语义）。注意两文件工作区已有未提交修改，实现时基于当前状态追加，不做整段重写。

## Risks / Trade-offs

- [manual 下 lint 不再于 drafted 期执行，用户阅读的草稿可能带未暴露的声明违规] → 人工晋升时仍执行完整 lint 并写 error；违规在按钮反馈与 STATE 中可见，拦截点后移但不消失。
- [CLI/dashboard 与 daemon 并发写 STATE.md 竞态] → 沿用 StateMachine 既有文件锁与 freeze/unfreeze 同款写入模式；晋升函数幂等防御（非 drafted 拒绝），双通道同时操作同一 spec 时后到者被拒绝。
- [手动晋升后 daemon 感知延迟（watcher 事件丢失时依赖 full_scan，间隔最长 30 分钟）] → 感知链路是既有机制（freeze/unfreeze 同款依赖），可接受；设计上不引入新请求文件类型以避免机制膨胀。
- [ApprovalModePanel 保存载荷覆盖 gates 段丢 approve_mode] → 保存时合并两键同一载荷提交（D5）；测试覆盖「改晋升模式不改审批模式」场景。
- [spec_drafted 事件在设置保存前已被消费（竞态窗口）] → 行为取决于 daemon 读到的新旧值，属于配置热更新的固有窗口（30s），可接受；用户可手动晋升兜底。

## Migration Plan

纯新增：配置键缺省 auto（缺省行为与现状逐字节一致），无数据迁移。部署 = 合并后按常规重启 daemon（新代码生效）。回滚 = 还原提交即可，`gates.promote_mode` 键对旧代码是无害的未知键（既有校验只对已知键报错——实现时确认未知键容忍性，若 gates 段有严格白名单校验需同步放开枚举新键）。

## Open Questions

（无——关键不确定点已在探索阶段确认：闸口单点性、外部 ready 感知链路、受管键两处白名单、CLI 入口独立于 fenixd.py。）
