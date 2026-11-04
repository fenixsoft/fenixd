<!-- knowledge: capability=concurrent-suite-isolation rev=2 sources=spec/archive/2026-09-19-fix-run-hang-amplification,spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md -->

# 并发套件隔离

同一主机多 worktree 并发执行测试/验证套件时的资源隔离规则，消除端口与临时资源争抢导致的伪失败。

## 现行规则

- 空闲端口分配不得存在「先申请、释放、再绑定」的 TOCTOU 竞态窗口：要么把已绑定的 socket 直接交给使用方，要么在最终绑定失败时按可重试策略重取；「探测到的端口」在被真正使用前不得处于无主状态而可被其他进程抢占。
- 端口来源可经环境变量覆盖（沿用 `FENIX_VERIFY_PORT` 语义）：调用方设置了端口相关环境变量时，端口采用该变量指定的值/段，而非自行探测。
- 同主机多个 worktree 并发执行全量套件须有隔离或串行手段——按 run/worktree 派生端口段与独立临时目录，或主机级互斥串行化——并在 implementer/repair 契约中引导使用；隔离策略不得依赖「机器负载恰好不高」的假设。
- 隔离/串行策略可观测：采用时在日志/run 文件中记录所用端口段或互斥获取结果，供事后复盘区分真实失败与资源争抢。
- 并发跑套件时各套件结果必须反映被测代码真实状态，因端口/临时目录/单例文件争抢产生的失败一律按伪失败处置，不判为被测代码缺陷。
- pytest basetemp 不得落在仓库工作区内：basetemp 落仓内有两个坑——临时目录让 git 向上发现主树仓根（tests/conftest 已把 `GIT_CEILING_DIRECTORIES` 钉到 basetemp 根切断），且并发 pytest 会话互删对方工作区产出假失败。取证/排查类 pytest 运行 MUST 显式独立 `--basetemp`（仓库外路径），不依赖缺省 basetemp。

## 溯源

- 2026-09-19 fix-run-hang-amplification（spec/archive/2026-09-19-fix-run-hang-amplification） — 确立端口分配无抢占窗口、环境变量覆盖与同主机并发全量套件的隔离/串行及可观测要求
- 2026-11-04 memory-distill-agent-prompt-rules（spec/knowledge/_inbox/done/memory-distill-agent-prompt-rules.md） — 折叠 pytest basetemp 隔离规则：basetemp 禁落仓库工作区（GIT_CEILING 切断 + 并发会话互删两坑），取证运行显式独立 --basetemp
