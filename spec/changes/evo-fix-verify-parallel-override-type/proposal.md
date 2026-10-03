# fix-verify-parallel-override-type

## 背景

android-station-port 人工裁决恢复（reset_verification）把 _verify_parallel_override 写成布尔 False（core/dashboard/data/admin_actions.py:1573 _RETRY_COUNTER_RESETS，引入自 add-human-adjudication-choices 40907bd8），而该字段契约是 int|None（读端 core/pm_engine/verification/pipeline.py:2100-2118、int 写点 escalation.py:439-441、复位点一律 None）。布尔归一清单（core/state_machine.py:559-588）不含该字段（只在 null 清单 :618），False 序列化进 STATE.md 后往返读回字符串 'False'，引擎 int() 解析失败降档告警「沿用配置并行度」（2026-10-03T17:10:26Z）。写入侧 _apply_updates_entry（state_machine.py:1373-1435）无逐字段类型校验；背书该写法的注释（admin_actions.py:1560-1567）与代码事实不符（unfreeze 实写 None、布尔清单不含该字段）。reset_verification 与 continue_auto_fix 每次人工裁决都重写 False，复发确定性高。

## 目标

1. 写侧归位：_RETRY_COUNTER_RESETS 该字段 False→None，与 unfreeze_spec 先例语义对齐；修正失实注释。
2. 解析侧归一：state_machine 为该字段登记 int|None 归一，非法形状写入前拒绝或归 None，杜绝 STATE.md 往返字符串化。
3. 读端留痕加固：解析失败告警补值形状（repr）与字段来源；不做布尔→并行度映射。

## 非目标

- 不做 _apply_updates_entry 全字段通用类型校验框架（全面加固另立）。
- 不改降档并行度 int 语义与 env 降档链路行为。

## 验收

- reset_verification 与 continue_auto_fix 处置后该字段为 null，STATE.md 往返读回 null，验证启动不再出解析告警。
- 注入 'False'/'true' 等字符串或布尔值：写入前被归一/拒绝并告警，读端告警含 repr 留痕。
- 既有 tests/test_verify_parallel_backoff.py 零回退。