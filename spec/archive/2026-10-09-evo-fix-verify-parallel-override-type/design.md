# 设计（fix-verify-parallel-override-type）

## 现状与根因

- 契约：int|None——读端 core/pm_engine/verification/pipeline.py:2105-2118（int() 解析、except 落告警、契约描述 :2100-2104 行内注释）；int 写点 core/pm_engine/verification/escalation.py:439-441；None 复位点 escalation.py:343-349、pipeline.py:1137/1289、state_machine.py:1779、fast_track.py:1065、legacy.py:502/612。
- 坏写点：core/dashboard/data/admin_actions.py:1573 _RETRY_COUNTER_RESETS 写 False；消费点 :1758-1770（reset_verification）、:2014-2031（_exec_continue_auto_fix）；背书注释 :1560-1567 两处失实（unfreeze 实写 None state_machine.py:1776-1779；布尔归一清单 :559-588 不含该字段，它只在 null 清单 :618——引入提交 26d819ba 只补了 null 清单）。
- 无写入校验：core/state_machine.py:1373-1435 _apply_updates_entry 无逐字段类型校验（对照 parse 侧 int 转换先例 :538-558）。
- 复发面：每次人工裁决（reset_verification/continue_auto_fix）都重写 False；本案警告全日志唯一一次系该动词低频。

## 方案决策

1. 写侧单行修正 False→None＋注释纠偏——最小且直击源头。
2. 双层归一，职责分离：写入侧在 update_spec/_apply_updates_entry（:1373-1435）为该字段加单字段形状守卫——布尔或字符串形状（'False'/'true' 等）拒绝并告警或归 None，不静默序列化进 STATE.md（单字段守卫，不属非目标排除的全字段通用框架）；parse 侧登记 int|None 归一（int 先例区 :538-558，null 兼容），覆盖存量 STATE.md 'False' 首读清洗。注意：parse 归一使往返读值由 str "2" 变 int 2（read_one→read_all 全量 parse 实证），既有 tests/test_characterization_verification.py:177 裸字符串断言须同轮更新。
3. 明确不做布尔清单注册（反模式：会把合法降档值 '2' 误转 False）与读端 'false'→max_parallel=1 映射（写入者真实意图是清零复位，映射会把复位扭曲成单线程验证；int(False)=0 会把并行度置 0，同为坏值）。
4. 读端告警现网已含 repr（pipeline.py:2114 `{_parallel_override!r}`）——仅确认不退化并补字段来源（值取自 spec attrs），无结构性改动。

## 风险

- 存量字符串化 STATE 值：归一逻辑需幂等清洗首读。
- 归一过宽掩盖真实坏值：拒绝＋告警优先于静默归 None。