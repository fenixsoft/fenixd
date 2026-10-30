# 合并增量（2026-10-30 人工全量核查）

折叠条目：2e931648887e、578511351dd9（主体）、848a8522bbe1、86ca884c46b3、dee3cabe83b1、fd64ff4d50de。

- 用户决策已执行（2026-10-30）：config.yaml night_quiet_window 已改为带引号 `"off"`（合法禁用态，`_night_quiet_window_disabled` 认字符串 off）。本 SPEC 仍立项：布尔/非法形态归一＋载入期 lint（config.py get_code_review_fix_config 校验清单唯漏此键）＋停用态每日一次 admin 消费通道（复用 code_fix.py:3505）。定性两存：守卫被关＝用户 10-19 有意（设计内）；「关不掉得干净」＝框架缺陷（裸 off 被 PyYAML safe_load 吃成 False，显式禁用分支在自然书写下不可达）。
- dsh salvage 判别子项（5785 第⑤点，独立代码缺口）：runner.py:511-527 判别只读 result 事件文本/terminal_reason，dsh 超时签名只在 stderr → api_timeout=False 误判、salvage 零触发（fenixd.log:1394 实证）。作附加验收场景。
- 86ca 权衡带入：false→off 同义化立场在 YAML 陷阱新证据下重估——裸 off 本就被解析器吃成 False，同义化反而消解告警压力。
- fd64 时间轴锚保留：10-20 05:48:18 人工 re-arm 与热重载日志逐秒咬合、06:10:44 首条非法值 WARNING——「off→false 转变时刻」唯一锚。
- 第 5 次击杀实证：10-30 04:32 code-fix-1793305048（fenixd.log:7935），派发 04:17:28 落缺省窗内，armed 即可拦下；「日程裕量」论已证伪。
