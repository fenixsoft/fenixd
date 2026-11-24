<!-- knowledge: capability=concurrent-suite-isolation rev=3 sources=spec/archive/2026-09-19-fix-run-hang-amplification,spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md,spec/knowledge/_inbox/done/basetemp-deletion-attribution.md -->

# 并发套件隔离

同一主机多 worktree 并发执行测试/验证套件时的资源隔离规则，消除端口与临时资源争抢导致的伪失败。

## 现行规则

- 空闲端口分配不得存在「先申请、释放、再绑定」的 TOCTOU 竞态窗口：要么把已绑定的 socket 直接交给使用方，要么在最终绑定失败时按可重试策略重取；「探测到的端口」在被真正使用前不得处于无主状态而可被其他进程抢占。
- 端口来源可经环境变量覆盖（沿用 `FENIX_VERIFY_PORT` 语义）：调用方设置了端口相关环境变量时，端口采用该变量指定的值/段，而非自行探测。
- 同主机多个 worktree 并发执行全量套件须有隔离或串行手段——按 run/worktree 派生端口段与独立临时目录，或主机级互斥串行化——并在 implementer/repair 契约中引导使用；隔离策略不得依赖「机器负载恰好不高」的假设。
- 隔离/串行策略可观测：采用时在日志/run 文件中记录所用端口段或互斥获取结果，供事后复盘区分真实失败与资源争抢。
- 并发跑套件时各套件结果必须反映被测代码真实状态，因端口/临时目录/basetemp 争抢产生的失败一律按伪失败处置，不判为被测代码缺陷。
- pytest basetemp 统一落项目内 gitignored 路径（`<项目根>/.fenix/` 下），不经系统 `/tmp/pytest-of-<user>/` 缺省位——多项目/多并发套件在该缺省位交叉争抢；进程级 `GIT_CEILING_DIRECTORIES` 钉到 basetemp 根，切断 git 经临时目录向上发现仓根。
- 未显式 `--basetemp` 的 pytest 会话，conftest 兜底根为 pid 唯一的 `<项目根>/.fenix/pytest-basetemp-<pid>`：每会话独占、互不交叉，宁可留残根也不互删；conftest setup 顺带清扫「目录名带 pid 后缀且归属进程已死」的残根防跨会话累积，活进程根与锁保护面裸共享根不得触碰。
- 会话收尾只 `rmtree` 自己自建的 pid 唯一根，调用方显式给定的 `--basetemp` 根不因任何会话收尾被删除。「一方收尾连根拔掉另一方在飞 tmp 树 → 幸存方 `TempPathFactory` 缓存 `_basetemp` 不重建 → 其后全部 tmp_path 用例 setup ENOENT」是批量 setup 假失败的完整形态，该删除路径已封死。
- 全量回归经 `bin/run_full_suite.py` 注入共享根 `--basetemp=<项目根>/.fenix/pytest-basetemp` 并以主机锁串行化，共享根仅供该持锁链使用；主机锁获取失败时回退注入 pid 唯一根继续执行（放弃串行保证但杜绝互删），回退必须留痕供复盘。
- pytest given-basetemp 语义为「会话首次 `getbasetemp()` 先 `rm_rf` 清空给定根再建」：共享根的清空只发生在持有主机锁的会话起跑点，每轮套件从干净目录起跑、不跨轮累积。
- 已缓存 basetemp 根被外力中途拔除时由每用例双层生命线兜底：setup 阶段前置钩子先于任何作用域夹具实例化重建工厂缓存的根，函数级守卫作次级兜底；属性缺失或重建失败一律 fail-open 放行，不把环境损失放大为用例失败。

## 代码锚点

- 主实现：`tests/conftest.py`
- 单源符号：`tests/conftest.py:_ensure_basetemp_alive`（双层生命线行为体）、`tests/conftest.py:_sweep_dead_basetemp_roots`（死根清扫）、`bin/run_full_suite.py:_with_basetemp`（全量回归 basetemp 注入单源）
- 消费方：`bin/run_full_suite.py`（全量回归共享根 + 主机锁串行化 + 锁失效回退 pid 唯一根）
- 守卫测试：`tests/test_basetemp_session_isolation.py`

## 溯源

- 2026-09-19 fix-run-hang-amplification（spec/archive/2026-09-19-fix-run-hang-amplification） — 确立端口分配无抢占窗口、环境变量覆盖与同主机并发全量套件的隔离/串行及可观测要求
- 2026-11-04 memory-distill-agent-prompt-rules（spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md） — 折叠 pytest basetemp 隔离规则：basetemp 禁落仓库工作区（GIT_CEILING 切断 + 并发会话互删两坑），取证运行显式独立 --basetemp
- 2026-11-22 basetemp-deletion-attribution（spec/knowledge/_inbox/done/basetemp-deletion-attribution.md） — 折叠 pytest-basetemp 共享根删除源定位结论（2026-11-22 907 例批量 setup 假失败）：兜底根 pid 唯一化、收尾只清自建根、双层生命线三层修复入库；废除「basetemp 禁落仓库工作区 / 取证运行须显式独立 --basetemp」旧规则（缺省兜根已会话唯一且安全）
