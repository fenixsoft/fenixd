## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: tests/test_dashboard_data.py
  kind: modify
```

## 1. 归档读侧回退

- [ ] 1.1 新增 `resolve_spec_dir(project_root, spec)` helper（core/dashboard/data.py）：spec 不匹配 `_SPEC_NAME_RE` 返回 None；`spec/changes/<spec>` 为目录返回活跃目录；否则在 `spec/archive/` 下按 `^\d{4}-\d{2}-\d{2}-{re.escape(spec)}(-\d+)*$` 匹配归档目录，命中多个取 `sorted()[-1]`；无命中返回 None
- [ ] 1.2 `get_spec_doc` 改用 helper：spec_dir 为 None 时五类文档返回 found=False；proposal/design/tasks/verification 的 target 基于 spec_dir 解析且防穿越校验改为 `target.is_relative_to(spec_dir.resolve())`；scenarios 分支传 `spec_dir / "specs"`；入口 raise 语义保留
- [ ] 1.3 `parse_tasks`/`tasks_note` 改用 helper：tasks_path 初值基于 resolve 结果回退到原 changes 拼接；implementing worktree 优先分支保持在前，overlay 逻辑不动

## 2. 回归测试与验证

- [ ] 2.1 tests/test_dashboard_data.py 新增归档回退用例：tmp_path 夹具构造活跃/归档（含冲突后缀变体）两种布局，断言归档 SPEC 五类文档 found=true 且内容与归档文件一致、多归档目录取名称排序最大、活跃 SPEC 结果不变、含穿越片段的 spec 参数仍被拒绝
- [ ] 2.2 运行 `python3 -m pytest tests/test_dashboard_data.py -q` 与相关 dashboard API 测试全绿；对真实归档 spec（如 add-fenix-dashboard）冒烟验证 `/api/spec-doc` 返回归档原文
