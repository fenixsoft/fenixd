# supervisor 导入期 argv 解析与拼写近似守卫的误击陷阱

## 背景

add-project-home-tab 实现 run 在 worktree 内执行有界全量套件（`bin/run_full_suite.py`），pytest 起跑数秒即 INTERNALERROR、整轮 exit 3；另一并行 worktree（spec 名不含 project）同入口正常。定位为 `bin/fenixd_supervisor.py` 的导入期行为与 worktree 路径的字符巧合交互，属测试基建路径敏感缺陷，已在同 run 内修复（argv[0] 判据）。

## 结论（当前事实）

- `bin/fenixd_supervisor.py` 的 `_resolve_project_root()` 在**模块导入期**执行（`PROJECT_ROOT, PROJECT_ROOT_SOURCE = _resolve_project_root()`），其 argparse `parse_known_args()` 缺省消费的是**导入方进程**的 `sys.argv`——被 pytest 测试文件导入（`tests/test_supervisor_hosting.py`、`tests/test_stale_code_selfheal.py`、`tests/test_supervisor_log_single_write.py`、`tests/test_systemd_hosting.py` 四处 `import bin.fenixd_supervisor`）时读到的就是 pytest 自己的命令行。
- 该函数内的「拼写近似守卫」（code-review 8acd5e209ae2）对 unknown 参数做「归一化后同时含 proj 与 root 子串」判定并 `sys.exit(2)`。pytest 入口注入的 `--basetemp=<绝对路径>` 恒含 `/root/`（root）；worktree 名含 `project`（proj）即两段齐备——守卫把宿主参数误判为拼错的 `--project-root`，import 期 SystemExit 被 pytest 收敛为 INTERNALERROR，全量套件 exit 3 秒败。**主树不触发**（主树 basetemp 路径 `/root/fenixd/.fenix/pytest-basetemp` 不含 proj），故只在 spec 名含 proj/root 字样的 worktree 全量回归中复现，极易误归因为环境性失败。
- 修复形态（已落 `bin/fenixd_supervisor.py`）：仅当 `Path(sys.argv[0]).name == "fenixd_supervisor.py"`（真实 CLI 入口，含测试经 monkeypatch sys.argv 模拟 CLI 的形态）才消费 argv；宿主进程一律 `parse_known_args([])` 跳过解析、按 `FENIX_PROJECT_ROOT`/cwd 兜底——与旧导入态行为一致（pytest argv 从不含 `--project-root`，argparse 结果同为 None）。
- 通用规则：**模块导入期 MUST NOT 解析宿主进程 argv**。脚本参数解析只属于真实 CLI 入口（argv[0] 为本脚本）；被测试/工具导入的模块其 import 期副作用必须能在任意 argv 下存活。`sys.exit()` 出现在 import 链上时，pytest 会以 INTERNALERROR（exit 3）整轮击穿，且秒败形态与端口/环境类伪失败高度同形——判因先看 INTERNALERROR 栈顶是否落在 `importtestmodule` 路径。

## 证据

- 复现：worktree `impl-add-project-home-tab-*` 内 `python3 bin/run_full_suite.py --timeout 3600` → `elapsed=9.3s rc=3`；同参裸跑取 INTERNALERROR 栈：`tests/test_stale_code_selfheal.py:32 import bin.fenixd_supervisor` → `fenixd_supervisor.py:86 sys.exit(2)`（suspect_args 分支），触发参数即 `--basetemp=/root/fenixd/.claude/worktrees/impl-add-project-home-tab-1794283107/.fenix/pytest-basetemp`。
- 对照组：并行 worktree `impl-add-maintenance-lane-provider-failover-*`（名称不含 proj）同一入口全程正常运行。
- 修复后：入口越过导入期进入运行期；四导入方测试文件 152 passed；`python3 bin/fenixd_supervisor.py --help` 行为不变（exit 0 用法输出）。
