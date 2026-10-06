# SPEC 归档查询视图
<!-- knowledge: capability=dashboard-spec-archive rev=3 sources=spec/archive/2026-09-09-add-spec-archive,spec/archive/2026-09-12-fix-archived-spec-doc-readback,spec/archive/2026-10-06-add-archive-state-migration -->

SPEC 的界面归档操作与已归档视图：归档 API 语义、archived 双源判定与归档产物回读。

## 规则

- 归档成功即迁出：目录移动成功后该 SPEC 的 STATE.md 条目迁出至归档清单 `.fenix/STATE.archive.md`（`archived_by=ui`）；迁出失败降级为响应中的告警字段，不回滚目录移动，条目保留在 STATE.md 等待存量回填下一轮迁出。
- 归档判定双源合取：`GET /api/specs` 为每个 SPEC 返回 `archived` 布尔——活跃目录 `spec/changes/<name>/` 不存在，且（活跃 STATE.md 或归档清单）有该条目，即判定已归档（与归档由界面、CLI skill、daemon 自动归档还是手动移动产生无关）；条目已迁出（仅清单有）的 SPEC 继续返回且 archived=true；活跃 STATE.md 与清单均无条目的名称（软删除残留）不返回。
- 归档确认与反馈：归档操作先弹确认框（说明 SPEC 将移入归档目录、可随时在「已归档」视图查看）；成功则提示并刷新列表（该 SPEC 从未归档视图消失、已归档视图可见），失败展示错误原因；取消无任何副作用。
- 归档视图切换：列表过滤区在「全部/仅需求/仅问题」控件右侧提供「未归档 / 已归档」切换控件（默认「未归档」），列表按所选归档状态过滤；已归档视图隐藏调度相关操作（调整优先级、冻结/解冻、归档），保留查看文档等只读能力，显示归档前状态与信息。
- 归档产物回读：已归档 SPEC（目录已移入 `spec/archive/`，条目通常已迁出归档清单）的文档与任务清单仍可从 dashboard 读侧访问——`/api/spec-doc` 对五类文档（proposal/design/tasks/verification/scenarios）从其归档目录读取并返回原文（found=true）；`/api/specs/<spec>` 详情的任务清单从归档目录 tasks.md 解析渲染（含完成状态，不显示空态）。
- 回读路径解析：归档目录命名解析与归档写侧规则一致（`YYYY-MM-DD-<name>`，含冲突时追加的数字后缀）；同名 SPEC 存在多个归档目录时取名称排序最大（最新）一份；活跃 SPEC（目录仍在 `spec/changes/`）完全维持现有行为；回退解析不引入路径穿越可能（穿越片段请求被拒绝，任何文件内容不返回）。

## 溯源

- 2026-09-09 add-spec-archive（spec/archive/2026-09-09-add-spec-archive） — 建立归档 API 语义（终态限定、目录移动命名、目标不覆盖）、archived 目录存在性判定、归档确认反馈与已归档视图切换控件
- 2026-09-12 fix-archived-spec-doc-readback（spec/archive/2026-09-12-fix-archived-spec-doc-readback） — 补齐归档 SPEC 读侧回访：五类文档与任务清单从归档目录读取、多归档取最新、防穿越保持
- 2026-10-06 add-archive-state-migration（spec/archive/2026-10-06-add-archive-state-migration） — 归档成功后迁出 STATE.md 条目至归档清单（archived_by=ui，失败降级告警）；archived 判定扩展为目录存在性 + 双源条目合取，已迁出条目仍可见可进详情
