# 错误归因降噪与取证判读

<!-- knowledge: capability=error-attribution-denoise rev=2 sources=spec/archive/2026-09-13-fix-provider-transient-backoff,spec/knowledge/_inbox/done/memory-distill-diagnostic-signatures.md -->

run 终态 error 消息拼装时的 CLI 诊断噪音过滤与死亡归因的取证判读：让死因字段不被无关信号误标，取证者拿到异常现象时按签名正确解读。

## 现行规则

- runner 在进程非零退出拼装 error 消息（取 stderr 末 5 行拼接）时，先过滤匹配 `^\claude-code:` 的 stderr 诊断噪音行；过滤后无剩余内容时回退 `Exit code: {returncode}` 形态（returncode 为实际退出码）。
- run 产物 jsonl 中的 stderr 原始事件行保持原样不过滤，取证现场完整。
- 瞬断判定与 dispatch 分类不得依赖降噪后的 error 字符串反推，必须使用原始 stderr 信号或结构化标记。
- exit 143 判读：成批同刻出现 = daemon shutdown 排水屠杀（框架主动终止，非 agent 自身失败）；离散个位数出现 = CLI 自身网关错误（该错误形态恒报 exit 1，143 非其信号）。
- exit 143 取证先排除 agent 自杀：`ps aux | grep "[p]ytest"` 类命令行 grep 会命中 agent 自己的 claude -p 进程（提示词文本嵌着命令字面量，grep 必中自身），对命中 PID 执行 kill 即自杀。框架侧已有 [killpg-self-guard](killpg-self-guard.md) 守卫，取证侧仍须先核对命中 PID 属谁再动手。
- 日志文案位置 ≠ 根因位置：归因前先查日志字符串的代码归属层——日志可能只在 legacy 兜底段执行，文案所示模块未必是行为发生处；对日志所指参数（如端口号），区分「源码声明的缺省值」与「实际注入方」，读对值的模块不一定是对值动手的模块。
- 「已修复问题复发」三轴取证：判定复发前对齐提交时间轴、事故时间轴、daemon 重启时间轴三条轴的锚点——「已修」可能只是修在从未重启的进程之外（旧码窗口内继续按旧逻辑出错）；同时核对冻结/失败计数是否存在同轮双计（验证轮与修复轮同轮各计一次会把单事故计成多次，形成假复发）。
- 在飞 run 识别：STATE 的 `implementer_run` 只在 run 到达完成态时写入；「implementer_run=null + status=implementing + 分支有提交」是在飞正常态而非异常，分支有提交或 tasks.md 已勾选均不等于 run 已结束。按 mtime 选 run 文件（`find_impl_run_file` 一类）与 STATE 权威源脱节——启动清扫会抬高僵尸 run 文件的 mtime，mtime 新鲜不作 run 存活的充分判据。

## 溯源

- 2026-09-13 fix-provider-transient-backoff（spec/archive/2026-09-13-fix-provider-transient-backoff） — 确立 error 拼装的 CLI 诊断行过滤、全噪音时退出码回退形态，以及「分类不得反推降噪文本」的口径
- 2026-11-04 memory-distill-diagnostic-signatures（spec/knowledge/_inbox/done/memory-distill-diagnostic-signatures.md） — 折叠取证判读签名族：exit 143 成批/离散二分、命令行 grep 自杀排除、日志文案归属层核查、「已修复复发」三轴时间轴对齐与同轮双计假复发、在飞 run 正常态识别（STATE 完成态才写 / mtime 脱节）
