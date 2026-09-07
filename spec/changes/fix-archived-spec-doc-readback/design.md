## Context

add-spec-archive 把归档实现为目录移动（`spec/changes/<name>/` → `spec/archive/YYYY-MM-DD-<name>/`）+ STATE.md 条目保留，列表侧以 `is_spec_archived`（活跃目录存在性）过滤出"已归档"视图。但读侧 `get_spec_doc`（core/dashboard/data.py:479）与 `parse_tasks`/`tasks_note`（data.py:1036/1117）硬编码 `spec/changes/` 路径，归档 SPEC 的文档页签与任务卡片因此空白。归档命名规则（与 `bin/fenix_archive.py` 同源）：`YYYY-MM-DD-<name>`，目标已存在时追加 `-{毫秒}`/`-{毫秒}-{n}` 后缀；软删除变体为 `<name>` 或 `<name>-<Unix秒>`（无日期前缀，且条目已从 STATE.md 移除，dashboard 不会请求）。

## Goals / Non-Goals

- Goals：已归档 SPEC 的五类文档（proposal/design/tasks/verification/scenarios）与任务清单在 dashboard 恢复可读；活跃 SPEC 行为零变化；防穿越强度不降。
- Non-Goals：不改归档/删除写路径；不为软删除命名变体提供读取（条目已不在 STATE.md，无入口）；不改前端；不改 API 响应结构。

## Decisions

### D1：共享目录解析 helper `resolve_spec_dir`

新增 `resolve_spec_dir(project_root, spec) -> Path | None`（core/dashboard/data.py），三处读侧共用：

1. spec 不匹配既有 `_SPEC_NAME_RE` → 返回 None（kebab-case 白名单天然排除 `..`/`/`，helper 内校验同时强化 parse_tasks 的健壮性）
2. `spec/changes/<spec>` 为目录 → 返回活跃目录（活跃优先，既有行为不变）
3. 否则遍历 `spec/archive/`，目录名匹配 `^\d{4}-\d{2}-\d{2}-{re.escape(spec)}(-\d+)*$`（日期前缀 + 可选冲突数字后缀；`re.escape` 防 spec 名含 `-` 引发歧义），命中多个取 `sorted()[-1]`（字典序最大 = 日期最新/后缀最大，与写入端冲突追加序一致）
4. 无命中 → None

### D2：`get_spec_doc` 切换到 helper + 目录内防穿越

`changes_root` 换为 `spec_dir = resolve_spec_dir(...)`：为 None → found=False（与原"spec 合法但目录不存在"行为一致）；`target = (spec_dir / f"{doc}.md").resolve()`，防穿越校验收紧为 `target.is_relative_to(spec_dir.resolve())`——相对 SPEC 目录自身校验，强度不低于原相对 changes_root 校验，对回退的归档目录同样生效。scenarios 分支传 `spec_dir / "specs"` 给 `_read_spec_scenarios`（其内部已有 is_dir 空态兜底）。入口的 `_SPEC_NAME_RE`/白名单 raise 语义保留不动。

### D3：`parse_tasks`/`tasks_note` 路径换 helper

`tasks_path` 初值改为 `(resolve_spec_dir(project_root, spec_name) or Path(project_root)/"spec"/"changes"/spec_name) / "tasks.md"`；implementing 状态的 worktree 优先分支保持在前（归档 SPEC 状态为 done/pushed，不会进入该分支）。`_should_overlay` 仅对 implementing 且有未完成任务叠加 run 状态，归档 SPEC 天然不触发，无需改动。`tasks_note` 同步换 helper（其存在性检查与 parse_tasks 同源）。

### D4：测试落点 `tests/test_dashboard_data.py`

临时项目夹具构造两种布局：活跃 SPEC（`spec/changes/<name>/`）与已归档 SPEC（目录移入 `spec/archive/2026-09-02-<name>/`，冲突后缀变体各一）。断言：归档 SPEC 五类文档 found=true 内容一致、任务清单按归档 tasks.md 渲染、多归档目录取最新、活跃 SPEC 结果不变、`..%2F` 类参数仍被拒。夹具在 tmp_path 内自建 STATE.md/目录，不触碰真实 `.fenix/`（用户级配置敏感测试三次复发教训：不 patch 用户级常量的测试必须自包含）。

## Risks / Trade-offs

- 归档目录 glob 每次请求都扫描（O(归档条目数)）：已归档视图访问频度低、单层目录规模有限，不引入缓存，保持实现简单。
- 字典序取最新在跨年大量归档下仍成立（YYYY-MM-DD 定宽）。
- `[operation]` 纯读侧：`get_spec_doc` found 语义从"仅活跃"扩展为"活跃优先归档回退"，无调用方依赖"归档 SPEC 必须 found=False"的旧行为（前端空态分支本就处理 found=true 正常渲染）。
