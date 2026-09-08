# add-draft-promotion-gate — SPEC 草稿晋升门控与人工放行

## Why

当前 SPEC 注册后（drafted）会被 PM Engine 自动晋升 ready 并立即派发实现，用户没有机会先阅读草稿。对于重要改动，用户希望在 daemon 调度前人工把关：阅读 proposal/specs/tasks，确认无误后再放行。需要一个配置项控制「drafted 是否自动晋升 ready」，并配套人工放行通道。

## What Changes

- 新增配置键 `gates.promote_mode`（枚举 auto/manual，缺省 `auto` 保持现行为，值语义对齐 `gates.approve_mode`）：
  - `true`（缺省）：现状不变，SPEC 注册为 drafted 后由 PM Engine 自动晋升 ready 并调度（含晋升前软化 + 声明 lint + tasks 可解析性 lint，行为完全不变）。
  - `false`：drafted SPEC 停留在草稿态，不晋升、不派发、不写 error（这是设计行为而非故障），记 info 日志说明等待人工放行。
- Dashboard 设置页「审批」页签新增「草稿晋升模式」单选（manual/auto，与 approve_mode 同构），放在现有审批模式设置上方。
- Dashboard 项目列表页（pages/projects/list.tsx，现有冻结/解冻操作所在处）的 spec 列表为 drafted 状态的 SPEC 新增「晋升 ready」操作（复用同一晋升链：软化 + lint + transition ready），lint 违规时停留 drafted 并把违规写入 STATE error（UI 可见）。
- 新增 CLI 命令 `bin/fenix_cli.py promote <spec> [--project <path>]`，与 Dashboard 按钮同一晋升语义。
- 晋升核心（软化 + lint + transition）提取为共享函数，自动晋升链与手动晋升通道共用，避免行为漂移。
- 同步更新 docs/help 下配置与治理文档。

## Capabilities

### New Capabilities

- `draft-promotion-gate`：`gates.promote_mode` 配置键（校验/缺省/热更新）、PM Engine 自动晋升闸口行为（开启=现状不变；关闭=drafted 停留且全路径覆盖）、设置页审批页签单选 UI（与 approve_mode 同构）、配置文档同步。
- `manual-spec-promotion`：人工放行通道——共享晋升函数（软化+lint+transition）、Dashboard 项目页「晋升 ready」按钮与 API、CLI `promote` 命令、lint 违规反馈、外部晋升后 daemon 感知派发闭环。

### Modified Capabilities

（无——`spec/specs/` 活跃目录为空，无需求级变更的既有能力；归档能力 add-spec-context-menu 仅覆盖 admin 唤起/优先级/删除菜单项，与本特性无冲突。）

## Impact

- `core/config.py`：新键校验（枚举 auto/manual）+ getter（缺省 auto）。
- `core/pm_engine/engine.py`：`_on_spec_drafted` 入口闸口（覆盖事件触发 / start_after 到期唤起 / full_scan recovery / 外部 drafted 写入全部路径）。
- `core/pm_engine/`（或 `core/` 下合适位置）：新增共享晋升函数模块。
- `core/dashboard/server.py` + `core/dashboard/data.py`：晋升 API；`data.py` 受管键白名单扩展 `gates.promote_mode`。
- `core/dashboard/static/src/`：设置页 `ApprovalModePanel.tsx`（单选）、项目详情页 spec 操作（晋升按钮）、`services/dashboard.ts`（API client）。
- `bin/fenix_cli.py`：新建 CLI 入口。
- `docs/help/08-config.md`（配置表）与 `docs/help/06-governance.md`（人工放行流程说明）。
- 测试：config 校验、pm_engine 闸口、dashboard API、晋升函数 lint 拦截。
