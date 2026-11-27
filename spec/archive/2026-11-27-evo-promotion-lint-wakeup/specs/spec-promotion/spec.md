# 能力：SPEC 晋升（spec-promotion）

## 概述

drafted 态 spec 晋升前的可解析性硬门（promotion lint）与拒绝后的恢复路径，是人工起草车道的第一接触面。lint 反馈必须一轮给全可修信息，修复落盘后必须有即时晋升唤醒，人工格式失误不应转化为 40 分钟量级管线延迟。

## 需求

1. lint 报告完整性：tasks.md 分组不可解析时，违规消息必须并列披露可测的 checkbox 任务行总数（item_count）与「分组修正后任务行还需补组号.序号编号」的后续提示；多类 lint（deliverables/tasks/title）由调用方既有聚合（promotion.py 按 msgs 固定顺序 `";".join`）按序并列披露，多类可测信息不得要求人工多轮往返。
2. 即时唤醒：status=drafted 且 STATE error 含「tasks.md 可解析性 lint 未通过」段（分段/子串匹配——该 error 由 promotion.py 按三类 lint 固定顺序 join 拼接，Deliverables 段恒居首，tasks 段可与前段并存，前缀匹配会漏纳多类违规并存的 spec）的 spec，其 tasks.md 文件变化时即时重评晋升——复用既有 spec_drafted 恢复出口，继承 start_after 门控与 promote_mode=manual 短路。
3. 唤醒卫生：监视面按「drafted 且 error 为 tasks.md lint 文案」预过滤，不得对全部 spec 目录做常驻扫描；lint 仍败重写同值 error 时抑制重复触发与重复日志。
4. 留痕：dashboard 侧清除 STATE error（clear_spec_error）时显式写一行留痕日志（含 spec 名与清空来源），弥补 dashboard 独立进程留痕不汇入 daemon 日志的缺口。
5. 兼容：lint 判据本身、30 分钟 full scan 兜底节拍、程序化起草车道（scheduling_kick 通道）行为均不变。

## 验收

- 构造「分组缺失+多条未编号 checkbox 行」的 tasks.md：单轮 lint 消息同时含分组形态要求与任务行计数。
- drafted+lint-error spec 的 tasks.md 修复落盘后，晋升重评在秒级发生；lint 仍败时无重复事件/日志风暴。
- promote_mode=manual 与非 lint error 的 drafted spec 行为不变；存量 lint 测试（tests/test_deliverable_lint.py、tests/test_task_artifact_ownership.py 零误拦守卫）零回归。
