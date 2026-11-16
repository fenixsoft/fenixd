# supervisor 运行时漂移检测（pid 存活门控）

## 信号语义

- signal_type：supervisor_runtime_drift，由 daemon 启动自检产生（kind=escalation）。
- 触发条件：.fenix/supervisor_runtime.json 的 started_at 早于本次 daemon 启动超过 SUPERVISOR_RUNTIME_DRIFT_SECONDS（24h），且通过 60 分钟去重窗。

## 分级判定（本能力新增 pid 门控，按序判定）

1. runtime 文件缺 pid 字段或 pid 不可解析（含解析结果为非正整数——os.kill(0/-N, 0) 探测的是进程组而非目标进程）：维持旧行为——severity=warning，「残留」叙事。
2. os.kill(pid, 0) 抛 ESRCH（进程不存在）：severity=warning，保留「疑似 runtime 文件残留自此前 supervisor 进程，建议重启 supervisor 刷新上报」叙事。
3. os.kill(pid, 0) 成功或抛 EPERM（进程存活）：读取 /proc 下该 pid 的 cmdline 做身份校验——
   - cmdline 包含「fenixd_supervisor」或 runtime 文件的 project_root 字符串：判「长寿伴生」，severity=info，文案「长寿 supervisor 伴生（daemon 多代重启所致），无需处置」——文案以整条成记录口径计（description/evidence/recommended_action 合并），记录级 recommended_action 同步为「无需处置」类文案，不得含「残留」「建议重启」「重启 supervisor」字样；
   - cmdline 可读但两者均不含（pid 已被复用）：按 pid 消失处理，severity=warning、「残留」叙事；
   - cmdline 读取抛 FileNotFoundError/ProcessLookupError（探活与读取竞态窗口内进程刚退出）：按 pid 消失处理，severity=warning、「残留」叙事；
   - cmdline 其他读取异常（权限/容器环境不可读）：按存活处理，severity=info、「长寿伴生」。

## 去重与留痕

- 60 分钟去重窗、PROJECT_LOG 留痕与去重标记逻辑不变；
- info 与 warning 均不进人工待处理队列（HUMAN_SEVERITIES 不变，warning 写入即自动 handled）。

## 边界约定

- supervisor 本机常态为长寿进程：告警文案不得把长寿伴生表述为异常或残留；
- runtime 文件唯一消费者是 daemon 启动自检，本能力不引入新的消费方。