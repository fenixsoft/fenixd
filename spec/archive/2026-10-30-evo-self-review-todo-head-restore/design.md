# design：self-review-todo-head-restore

## 落点

- core/self_review.py：新增模块级助手 + 三处回写接入。
- core/config.py：get_self_review_config（2103-2131 行）加开关。
- core/dashboard/routes/settings_routes.py：_write_project_doc（408 行）与 POST /api/todo（441 行）。

## 助手设计（self_review.py）

```python
def _load_existing_with_head_rescue(todo_path: Path, project_root: Path, restore_enabled: bool) -> str:
    existing = 读工作树（缺失/异常按现状回退 ""）
    if not restore_enabled or existing.strip():
        return existing
    head = subprocess.run(["git", "-C", str(project_root), "show", "HEAD:.fenix/todo.md"],
                          capture_output=True, timeout=30, ...)
    if head.returncode == 0 and head.stdout.strip():
        logger.warning("todo.md 工作树为空而 HEAD 版非空，回写前自 HEAD 恢复基线（%d 字节）；如系有意清空请复核或设 todo_head_restore=false", len(head.stdout))
        return head.stdout.decode("utf-8", "replace")
    return existing
```

- _append_todo._do（2069-2089）、_skip_review._do（1445-1457）改为经该助手取基线；_remove_resolved._do（1876 起）同型复用。锁仍由外层 with_file_lock 持有，恢复+写在一次锁内原子完成。
- git show 口径与 _commit_todo 一致；stdout 解码失败按回退处理。

## 配置（config.py）

- get_self_review_config 返回体加 todo_head_restore = sr.get("todo_head_restore", True)；紧邻 read_todo（2123 行）放置。消费点经既有 config 传递链下发，不新增全局读取。

## dashboard 端点（settings_routes.py）

- _write_project_doc 对 todo.md 目标包 with_file_lock（fs_utils 同一把 .todo.md.lock）；写成功后 logger.info 落「dashboard 覆写 todo.md（N 字节）」；content 为空而 HEAD 版非空时 logger.warning；git show 失败（项目非 git 仓库/超时）时跳过 HEAD 对比、按现状写、不落 WARNING——留痕尽力而为，不阻塞保存。非 todo.md 目标行为不变。

## 边界与取舍

- 不翻转 read_todo 缺省：全局成本/行为变更且已有 fallback-honesty 诚实陈述兜底，独立成题。
- 恢复基线取 HEAD 而非最后一个非空提交：HEAD 即 daemon 上次回写结果（回写后即时入库，见 evo-add-todo-marker-commit-on-write），语义最简；历史提交 e5001d9f（2026-10-09 最后完整版，119 行/8 日期节）的一次性数据修复（并入 10-10 节）走人工运维。
- 第四个持锁写入者 core.evolution.write_todo_marker 不接入恢复：其写入以「当前文本中定位到条目」为前置（evolution.py write_todo_marker._do，定位不到条目即跳过不写），空/缺文件上天然 no-op，不构成空基线覆写路径。「全部写入路径」指全部内容损失型回写路径（self_review 三处 + dashboard 覆写端点）。
- 恢复与「有意清空」的冲突由 R2 开关+WARNING 双保险：默认恢复可能复活用户刚清掉的文件，但留痕明示了恢复动作与豁免路径，不静默吞掉任何一方意图。
- subprocess 失败/超时全部静默回退，保证台账写入主路径永不因防护而失败。