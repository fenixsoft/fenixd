# 自省车道删除禁令（basetemp 事故纵深防御第三层）

日期：2026-11-22。关联：`basetemp-deletion-attribution.md`（删除者归因：每日自省 agent 主树裸跑 pytest 核销「timelib 守卫已回绿」条目，触发事故版 conftest 收尾 rmtree 共享 basetemp 根，连爆两晚 11-21/11-22 全量回归）。

## 三层防线全景

1. **根因层（已修，conftest）**：兜底 basetemp 改 pid 唯一根 `pytest-basetemp-<pid>` + 共享根不再收尾删除 + `_ensure_basetemp_alive` 双层生命线（commit 链 687b722c6…1f44d155a）。裸 pytest 复跑本身合法，不再拦。
2. **机械层（本防线，硬兜底）**：PreToolUse Bash hook `.fenix/hooks/block-main-tree-delete.py`（gitignored 自举物）——`FENIX_RUN_WORKTREE` 非空（worktree lane）放行；主树 run（自省/admin 巡检/inplace 修复）deny 删除类命令：rm 全形态（含单文件，宁枉勿纵）、`shutil.rmtree`/`os.remove`/`os.unlink`/`.unlink(`/`rmtree(`、`git clean`/`git rm`/`git worktree remove`、`find -delete`/`-exec rm`、独立 `unlink`。注册 `.fenix/agent-settings.json`（第 4 个 hook，matcher=Bash）。测试 `tests/test_block_main_tree_delete_hook.py`（17 例）。
3. **提示词层（软防线）**：`agents/self-review.md` 铁律新增第 4 条——禁止删除任何文件/目录；核查一律只读，复跑测试允许。

## 关键口径

- **pytest 复跑不拦**：自省核销「已回绿」类条目需要运行时证据，复跑是正当核查；事故根源是 conftest 删共享根，不是复跑本身。
- **worktree lane 豁免**：implementer/fix 等沙箱内删除自家文件是正当操作，归 `block-main-tree-write`（写盘隔离）语义管。
- **生效时机**：`agent-settings.json` 与 `agents/self-review.md` 均为 spawn 时新鲜读取（`_claude_settings_path` / `_load_agent_template`），无需重启 daemon。
- **已知边界**：命令串级匹配不做 shell 解析，`echo rm x` 类无害串会误拦（主树 run 无正当场景，接受）；hook 只拦 agent 直接键入的命令，拦不住框架代码自身的清理行为（那归根因层管）。

## 排查结论（Q1：自省为什么跑 pytest）

- 自省的闭环判定（`agents/self-review.md` 闭环判定节）要求「判定依据 MUST 可核实」，对「X 已回绿/已修复」类条目，最强证据是复跑对应测试；11-21 起台账首次出现此类核销对象（timelib 守卫条目），此前 11-10..20 十一晚 pytest 调用为 0（闭环凭 commit hash/spec 名即可裁决）。
- 模板原文本建议「必要时只读查看 git log 与源码核实」，未禁止跑测试——agent 自主选择了更强的运行时证据。现三层防线把「复跑合法、删除非法」的边界机械化固定。
