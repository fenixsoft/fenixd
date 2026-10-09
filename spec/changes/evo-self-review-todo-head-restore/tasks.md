## Deliverables

```yaml
- path: core/self_review.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/dashboard/routes/settings_routes.py
  kind: modify
- path: tests/test_self_review_todo_head_restore.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/self_review.py：新增共用助手 _load_existing_with_head_rescue——工作树为空/缺失且 todo_head_restore 开启时，用 git show HEAD:.fenix/todo.md（subprocess，30 秒超时，与 _commit_todo 同口径）读回基线并 WARNING 留痕；git show 失败静默回退现状；_append_todo._do、_skip_review._do 改经该助手取基线，_remove_resolved._do 同型复用。
- [ ] 1.2 core/config.py：get_self_review_config 增加 todo_head_restore 配置（缺省 true，紧邻 read_todo 放置，严格 bool 校验——非 bool 值回退缺省，同 read_todo 既有范式），经既有配置传递链下发到三处回写消费点；为 false 时跳过恢复且不落恢复 WARNING。
- [ ] 1.3 core/dashboard/routes/settings_routes.py：_write_project_doc 对 .fenix/todo.md 目标写入时持 with_file_lock 同一把锁，成功写入落 INFO 留痕（路径+字节数），覆写为空而 HEAD 版非空时落 WARNING；git show 失败（项目非 git 仓库/超时）时跳过 HEAD 对比，不阻塞保存；非 todo.md 目标行为不变。

## 2. 测试

- [ ] 2.1 tests/test_self_review_todo_head_restore.py：覆盖四态——工作树空而 HEAD 非空（恢复基线后追加+WARNING）；工作树有内容（与现状一致不引 HEAD）；git show 失败（静默回退按空基线写）；todo_head_restore=false（不恢复无恢复 WARNING）。
- [ ] 2.2 tests/test_self_review_todo_head_restore.py：dashboard 端点写入加锁与留痕用例（写成功 INFO、覆空 WARNING），形态对齐既有 tests/test_dashboard_todo_api.py。
- [ ] 2.3 tests/test_daily_self_review.py、tests/test_self_review_todo_fallback.py 与 tests/test_dashboard_todo_api.py 既有用例回归通过（python3 -m pytest tests/test_daily_self_review.py tests/test_self_review_todo_fallback.py tests/test_dashboard_todo_api.py -q；test_dashboard_todo_api.py 直接覆盖 1.3 改动的 POST /api/todo 路径）。