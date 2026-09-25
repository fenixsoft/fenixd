# 设计：add-per-test-timeout-gate

## Context

- 回归命令形态由项目声明（`core/regression.py` 框架无关，命令来自 `verify.yaml` 的 `regression` 段），仓内当前没有任何 pytest 配置文件（无 pytest.ini / pyproject.toml / setup.cfg）
- `pytest-timeout` 2.4.0 已在运行环境
- 事故锚点：drain-window 测试替身真自旋（6 用例 × 60s 烧满替身超时），回归 250s→615s，~41 次累计 +4.1h（2026-09-25 审计）
- 验证链（spec 场景验证）与回归车道共用 pytest 入口，仓级配置对两者同时生效

## Goals / Non-Goals

**Goals:**
- 单用例 10s 硬超时成为机械规则，超时失败信息可机读
- 豁免必须显式登记且带理由，清单本身被机械校验
- 存量套件在规则下全量通过（一次性处置完毕）

**Non-Goals:**
- 不提供全局放宽阈值的配置项（防止规则被静默稀释）
- 不治理用例间的套件级总时长（只管单用例上限）
- 不改动回归车道的命令拼接与锁语义

## Decisions

- **D1 仓级 `pytest.ini` 单源**（`timeout = 10`、`timeout_method = signal`），不改回归命令拼接。理由：任何 pytest 入口（回归/验证链/本地开发/worktree）一致生效，单点维护；替代方案（verify.yaml 命令追加 `--timeout`）只覆盖回归一个入口。
- **D2 signal 方法而非 thread 方法**：signal（SIGALRM）只中断主线程，用例判失败后会话继续；thread 方法超时会 dump 栈后 `os._exit` 整个 pytest 进程，等于一次慢用例杀掉整场回归。本仓用例均为纯 Python 替身/IO，SIGALRM 可中断；xdist worker 若未来启用，其用例同样运行在 worker 进程主线程，signal 仍适用。
- **D3 豁免清单 `tests/timeout-allowlist.yaml` + conftest 注入**：conftest 的 `pytest_collection_modifyitems` 按 nodeid 匹配清单条目，注入 `pytest.mark.timeout(N)`；`tests/test_timeout_gate.py` 内置 schema 校验用例（`reason` 非空、`timeout_seconds > 0`、YAML 可解析），违规即测试失败。理由：豁免是规则的安全阀，必须显式、留痕、可校验。
- **D4 超时行为验证用 pytester 内联样例**（临时目录内生成超阈值 `sleep` 用例断言 FAILED + 超时标识），不向常驻套件引入慢用例（否则门自身会拦它）。样例内层会话 MUST 显式压低阈值（如 `-o timeout=2` 配 `sleep(3)`），不得照搬全局 10s/15s 数字：外层验证用例自身受同一 10s 门约束，真等 15s/30s 会先被外层门判超时；且 pytester 临时目录落在仓内 basetemp（`.fenix/pytest-basetemp`，见 conftest `_isolated_basetemp_cleanup`），内层 pytest 会向上发现仓根 `pytest.ini` 继承 10s 门——显式 `-o` 覆盖是唯一可靠控制。

## Risks / Trade-offs

- [SIGALRM 无法中断 C 扩展深处的阻塞] → 本仓现无此类用例；若未来出现，处置方式是拆分/改造该用例或走豁免清单登记更长时限（thread 方法的整进程代价不适合作为全局方法）
- [10s 误杀偶发抖动慢用例] → 偶发复发按回归失败走既有 code-fix 链；确需更久的用例走豁免清单
- [signal 中断后残留后台线程] → 现有 conftest 已有进程级清理，不新增处理
- [junit 读侧对 timeout 失败的归类] → pytest-timeout 的失败在 junit XML 中是普通 failure，失败消息含 `Timeout` 标识；回归读侧无需改动

## Migration Plan

合入即生效（配置文件随分支合回主树）。存量处置在实现分支内完成（任务 2.3 全量跑一遍）；合并后首轮回回归自然复验。
