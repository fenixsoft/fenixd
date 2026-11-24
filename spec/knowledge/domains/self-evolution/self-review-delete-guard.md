<!-- knowledge: capability=self-review-delete-guard rev=1 sources=spec/knowledge/_inbox/done/self-review-no-delete-guard.md -->

# 自省车道删除禁令

主树 run（无 worktree 的 agent run：每日自省、admin 巡检、inplace 修复等）一律禁止执行删除类命令；核查只读、复跑测试合法。与测试套件侧的 basetemp 会话隔离规则（test-engineering 域「并发套件隔离」）构成同一事故面的纵深防御，本页承载其中机械层与提示词层。

## 现行规则

- 主树 run 删除禁令由 PreToolUse Bash hook 机械执行（`.fenix/hooks/block-main-tree-delete.py`）：对整条命令串做删除模式判定，任一模式命中即整条 deny 并回执纠偏文案（指引改用只读核查；确需删除时在 SPEC/任务文本中显式申请，交人工或 worktree 车道执行）。拦截面覆盖：rm 全形态（含单文件 rm——主树 run 无正当删除需求，宁枉勿纵）、Python 进程内删除（`shutil.rmtree(`、`rmtree(`、`os.remove(`、`os.unlink(`、`.unlink(`）、git 删除族（`git clean`、`git rm`、`git worktree remove`）、find 删除族（`-delete`、`-exec rm`）、独立 `unlink` 命令。
- 车道判别以 `FENIX_RUN_WORKTREE` 环境变量为唯一开关：非空（worktree lane，如 implementer/fix）放行——沙箱内删除自家文件是正当操作，写盘隔离归 `block-main-tree-write` 语义管辖；空或缺失（主树 run）才做删除判定。
- 匹配口径为命令串子串/正则匹配，不做 shell 解析：`echo rm x` 类无害串会误拦——主树 run 不存在合法删除场景，接受宁枉勿纵的误拦代价。
- pytest 复跑不拦：自省核销「X 已回绿/已修复」类台账条目需要运行时证据，复跑对应测试是正当核查手段；事故根源是删除共享状态的行为而非复跑本身。`git log/diff/show` 等只读核查、写文件、后台任务同样在放行面内。
- 生效时机为 spawn 时新鲜读取：hook 注册（`.fenix/agent-settings.json`，PreToolUse matcher=Bash）与自省提示词模板均在派发时装载，改动即对后续 run 生效，无需重启 daemon。
- 提示词层软防线与机械防线同口径：`agents/self-review.md` 铁律禁止删除任何文件/目录（rm、shutil.rmtree、os.remove/unlink、git clean、find -delete 等一律不执行），核查一律只读、复跑测试允许——测试自身的临时目录由框架隔离（pid 唯一 basetemp），不触碰主树共享状态。
- hook 的能力边界：只拦 agent 直接键入的 Bash 命令，拦不住框架代码自身的清理行为——该面由测试套件侧隔离规则管辖（conftest 兜底根 pid 唯一、会话收尾只清自建根、共享根不收尾删除）。

## 代码锚点

- 主实现：`.fenix/hooks/block-main-tree-delete.py`（PreToolUse Bash hook，删除模式判定与 deny 回执）
- 注册：`.fenix/agent-settings.json`（PreToolUse matcher=Bash，gitignored 自举物）
- 提示词层：`agents/self-review.md`（铁律「禁止删除任何文件/目录」条款）
- 车道判别 env 注入：`core/agent_runner/harness/claude_adapter.py`（`FENIX_RUN_WORKTREE` = 本次 run 的 worktree 绝对路径，worktree lane 豁免判据）
- 守卫测试：`tests/test_block_main_tree_delete_hook.py`

## 溯源

- 2026-11-22 self-review-no-delete-guard（spec/knowledge/_inbox/done/self-review-no-delete-guard.md） — 折叠自省车道删除禁令三层防线（conftest 根因层另见 test-engineering 域并发套件隔离页）：PreToolUse hook 机械拦截删除类命令、FENIX_RUN_WORKTREE 车道豁免、自省提示词铁律只读核查、pytest 复跑合法边界、spawn 时生效口径与 shell 解析缺席的误拦接受度
