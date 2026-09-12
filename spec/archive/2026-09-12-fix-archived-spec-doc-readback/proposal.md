## Why

add-spec-archive 落地了归档移动（`spec/changes/<name>/` → `spec/archive/YYYY-MM-DD-<name>/`）与列表"已归档"视图，但读侧未同步接线：`get_spec_doc` 与 `parse_tasks`/`tasks_note` 仍硬编码活跃目录 `spec/changes/`，导致已归档 SPEC 在 dashboard 中五类文档页签（proposal/design/tasks/verification/scenarios）全部空白、详情页任务卡片为空。归档确认弹窗承诺"可随时在已归档视图查看"，实际却看不了，且归档文档本身完好保留在磁盘（已实证：`spec/archive/2026-09-02-add-fenix-dashboard/proposal.md` 存在而 API 返回 found=False）。

## What Changes

- `get_spec_doc`（core/dashboard/data.py）增加归档路径回退：活跃目录缺失时，按归档命名规则（`YYYY-MM-DD-<name>` 及冲突后缀）在 `spec/archive/` 下解析该 SPEC 的目录，五类文档（proposal/design/tasks/verification/scenarios）从归档目录读取
- `parse_tasks` / `tasks_note` 同样增加归档回退：活跃目录缺失时从归档目录读 tasks.md，详情页任务卡片恢复展示
- 防穿越校验保持同级强度：回退路径解析后必须仍位于归档根目录内，杜绝 `..` 拼接越界
- 多个同名归档目录（日期前缀不同/冲突后缀）时按名称取最新一份，行为确定
- 活跃 SPEC（目录仍在 `spec/changes/`）行为完全不变；纯读侧改动，不动归档/删除写路径

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `dashboard-spec-archive`: 新增"归档 SPEC 内容仍可读"需求——已归档 SPEC（STATE.md 条目保留、活跃目录已移入归档）的文档页签（proposal/design/tasks/verification/scenarios）与任务清单 SHALL 从归档目录读取并正常展示；活跃 SPEC 行为不变；防穿越校验对回退路径同样生效。

## Impact

- `core/dashboard/data.py`：`get_spec_doc`、`parse_tasks`、`tasks_note`（新增一个共享的 SPEC 目录解析 helper，活跃优先、归档回退）
- API 契约不变：`/api/spec-doc`、`/api/specs/<spec>` 响应结构不变，仅 `found`/内容来源扩展
- 前端无改动（已归档视图与文档页签已存在，只是此前拿到 found=False）
- 回归测试：`tests/` 下针对归档回退新增用例（临时项目夹具构造活跃/归档两种布局）
