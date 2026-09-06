## Why

SPEC 提交后立即进入队列被 daemon 拾取，用户无法控制启动时机（如深夜 token 峰谷、错峰执行、等待依赖就绪）；冻结作为唯一人工暂停手段只能永久冻结、必须人工解冻，缺少「到点自动恢复」的半自动模式。两者共同导致：用户要么放任 spec 立即烧钱，要么冻结后忘记解冻造成积压。

## What Changes

- 新增 SPEC 定时启动机制：提交时（`/fenix-new` 参数）可指定 `start_after` 时间点，未到期 spec 保持 `drafted`/`ready` 但不被 daemon 拾取；到期后自动进入正常调度
- `start_after` 以 STATE.md entry 字段为单一事实源（ISO8601 UTC），支持绝对时间与相对时长（`+2h`）两种写法
- Dashboard spec 列表展示定时启动 spec 的等待倒计时，并支持在列表上查看/修改/清除 `start_after`
- 冻结 spec 新增「冻结管理」弹窗：对已冻结 spec 可在「永久冻结（人工解冻）」与「定时解冻（设置恢复调度时间）」间切换
- 定时解冻以 entry 字段 `frozen_until`（ISO8601 UTC）记录，daemon 到期后自动解冻并恢复冻结前状态；「永久冻结」即现有冻结语义（`frozen_until` 为空）
- 解冻恢复逻辑复用现有 unfreeze 语义（从冻结 error 中解析「原状态 X」恢复并清空 error）

## Capabilities

### New Capabilities
- `scheduled-spec-pickup`: SPEC 定时启动——`start_after` 字段契约（写入路径：fenix-new 参数 / dashboard 修改；存储：STATE.md entry）、调度器到期门控、到期后正常拾取、列表倒计时展示与修改入口
- `scheduled-spec-unfreeze`: 冻结定时解冻——冻结管理弹窗（永久↔定时切换）、`frozen_until` 字段契约、daemon 到期自动解冻（恢复冻结前状态）、解冻结果记录与展示

### Modified Capabilities

（无——现有冻结/解冻、spec-context-menu、spec-archive 能力的需求行为不变，本次仅在其上叠加定时维度）

## Impact

- **调度器**：`core/pm_engine/dispatch.py` / `engine.py` 派发候选筛选新增 `start_after` 门控（对齐 `_dispatch_backoff_until` 的既有跳过模式）；到期自动解冻需新增定时器 + 周期扫描兜底
- **状态机**：`core/state_machine.py` `add_spec`/`update_spec` 支持新字段透传（`start_after`、`frozen_until`）
- **Dashboard 后端**：`core/dashboard/data.py` 新增/扩展 freeze-config 与 start_after 读写函数；`core/dashboard/server.py` 新增 API 路由
- **Dashboard 前端**：`core/dashboard/static/src/pages/projects/list.tsx`（菜单项、倒计时列、弹窗）、`services/dashboard.ts`（新 API 封装）
- **fenix-new 流程**：`/fenix-new` skill 支持定时参数并写入 STATE.md 注册调用（Agent 行为约定，非代码文件）
- **状态文件**：STATE.md entry 新增两个可选字段，缺省 null，存量 spec 零迁移
