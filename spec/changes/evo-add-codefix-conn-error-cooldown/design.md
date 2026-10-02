# design — add-codefix-conn-error-cooldown

## D1 分类挂载：沿 api_timeout 单源先例

runner 异常挂载块（runner.py:5590-5608，已挂 exc.api_timeout/api_error_status/result_text）旁新增连接类布尔。判据三条件与依据：
- terminal_reason == "api_error"（is_api_timeout_signature 第一分支，runner.py:402-416；实测两个失败 run 的 result 事件均为 terminal_reason='api_error'）；
- exit_code != 0；
- result_text 命中连接类词表：**新增车道本地词表常量**（`CODE_FIX_CONN_ERROR_PATTERNS`，与 SWITCH_ERROR_CONN_PATTERNS 并列置于 provider_circuit.py），形态覆盖「Can't reach the API server」「ENOTFOUND」，并纳既有连接类形态（connection/connect + refused|reset|error|timeout、name or service not known 等）——已实测共享词表对本死因文本全部漏判。MUST NOT 扩充共享 SWITCH_ERROR_CONN_PATTERNS：该词表被 classify_switch_error（provider_circuit.py:418）消费，runner.py:2931 以其判定驱动 spec/impl 车道切链与 provider switch 短冷却，扩充即改变 spec/impl 车道既有切换行为，违反 proposal Non-Goal；且 ENOTFOUND 属本地 DNS 故障，切链无济于事只会烧尽链候选。

签名识别严禁裸匹配 stderr：unrecognized_model 是 CLI_STDERR_NOISE_TEXT_PATTERNS（provider_circuit.py:101-103）登记的 glm/deepseek 定噪行，成功 run 同样在场（5 个归档 jsonl 实证），todo 建议的「unrecognized_model 行 + exit 1」在 glm 链上等价于「exit 1 即命中」，语义与告警文案都会错。

## D2 信封透传

CodeFixResult（maintenance_runs.py:2158-2191）新增 conn_error 布尔与 result_text 字段（一并透传，供告警 evidence 与单测）。抄传点：run_code_fix except 块（maintenance_runs.py:2458-2474，现只取 api_timeout/exit_code/stderr_lines）。

与 evo-code-fix-api-timeout-salvage 的分工：api_timeout 布尔保持「现场抢救」触发语义不变；conn_error 只驱动冷却，不参与 salvage 判定。两布尔可同时为真（api_error 是 api_timeout 的宽判分支），互不掣肘。

## D3 冷却闸门挂 checkpoint，不挂 _resubmit

checkpoint（code_fix.py:2544）是全部激活路径的唯一共用投递入口（full scan 末尾兜底 event_bus.py:267、新条目激活 maintenance_runs.py:1651、自驱动 _resubmit code_fix.py:2997、事件驱动重试 code_fix.py:3265 均汇入），闸在这里才能同时拦住「full scan 在窗口内再触发的批次」；_resubmit（:2992）只覆盖自驱动一路。守卫形态仿 _in_flight 单飞检查，位于投递块（:2911-2983）之前。

冷却时长：import PROVIDER_SWITCH_COOLDOWN_SECONDS（provider_circuit.py:44）；配置键 admin.code_review_fix.switch_cooldown_seconds，读取与防御转换仿 _orphan_grace_minutes（code_fix.py:3205-3232：负值/NaN/inf 回退缺省，0 合法表示关闭）。定时器案（threading.Timer 延迟 resubmit，先例 admin_monitor.py:1321-1379）对自驱动车道是多余机制，不取。

## D4 冷却态持久化

fix-progress.json（FIX_PROGRESS_REL，code_fix.py:70）新增 switch_cooldown_until（epoch 秒）。写路径复用 write_progress（:227，原子合并写；chain_run_ids 持久化先例 :3786-3789）。选持久化而非内存的理由：full scan 跨重启仍要被拦；观测期内 daemon 多次重启，内存态会在残余窗口内漏拦。

## D5 告警

AdminStore.append（core/admin_store.py:418）写 kind=SIGNAL；车道内五个同构先例（write_regression_failed_alert 等，code_fix.py:2130-2288）。新 signal_type：code_fix_switch_window_deferred（severity=warning）。拒写走 _log_alert_rejected（:2041）留痕。解除告警无后台定时器写入口：由冷却到期后**首个通过守卫的 checkpoint** 补写一条（evidence 携带实际推迟时长）；冷却期内无后续 checkpoint 通过（台账清空空转）则不写解除。

## D6 跨日同刻指纹升级

admin_monitor daemon_errors 指纹记账（现有「同指纹 ERROR ≥2 次/10 分钟窗」判定）增加第二维度：保留每指纹最近一次失败终态时刻，新失败与上次跨日差在 24h±5 分钟内即升级 escalation（绕过已知指纹 30 分钟冷却）。4 天样本时刻差 <2 秒，容差充裕。不新造告警通道。

## D7 风险

- 词表误报面：连接类词表命中即冷却 300 秒，误报代价 = 车道停 5 分钟，可接受；不设自动豁免。
- 冷却与链收敛竞态：冷却期内台账清空（open=0）时 checkpoint 本就不投递，冷却字段残留无害（过期即失效）。