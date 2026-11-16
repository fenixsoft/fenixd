# 提案：supervisor 漂移告警补 pid 存活门控

## 背景与问题

daemon 启动自检的 supervisor_runtime_drift 判定（fenixd.py 启动自检段，现 6536-6605 行，漂移比较在 6580-6605）只比较 runtime 上报时间与 daemon 启动时间差（阈值 24 小时），从不检查上报文件所载 pid 是否存活。本机常态是 supervisor 长寿数天、daemon 多代重启：每次超 60 分钟去重窗的 daemon 重启都产出 1 条 warning 级告警，证据文案固定写「疑似 runtime 文件残留自此前 supervisor 进程，建议重启 supervisor 刷新上报」——对存活进程指认残留并给出重启活进程的错误指引。

2026-09-27 至 2026-11-13 已累积 79 条此类告警（当前 admin_alerts.json 56 条 + 归档 23 条），近 8 天连发 39 条、11-10 单日 9 条；fenix-desktop 项目 runtime 文件所载 pid 3219849 经 ps 核实存活 8 天，叙事被直接证伪。同主题归档 SPEC 2026-10-04-evo-supervisor-drift-log-dedup 只治理了 PROJECT_LOG 留痕刷屏，未治理告警成条本身，归档后仍连发。

## 目标

- drift 告警前先核 runtime 文件 pid 存活与 project_root 归属；
- 进程存活：降级 info，文案改为「长寿 supervisor 伴生」，移除「建议重启 supervisor」指引；
- pid 消失：维持 warning 与「残留」叙事，保留真实残留检出能力；
- pid 字段缺失或不可解析：维持现行为，不回归。

## 非目标

- 不改 supervisor 侧上报节奏与 runtime 文件结构；
- 不改排水一致性检查（sigkill_wait 口径）与 60 分钟去重窗；
- 不改告警升级链路与人工队列准入（HUMAN_SEVERITIES）。

## 验收标准

- 存活 pid 成条为 info，且文案不含「残留」「建议重启」字样；
- 死亡 pid 成条为 warning，保留「残留」叙事与重启指引；
- runtime 文件缺 pid 字段时行为与现版本一致；
- 既有漂移/去重测试全绿。