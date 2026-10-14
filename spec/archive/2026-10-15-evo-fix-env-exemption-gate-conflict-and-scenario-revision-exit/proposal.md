## 背景

2026-10-05 potplayer-base 项目 pack2-official-encoder 验证链：09:23:11Z 第一轮失败被裁决 grant_env_exemption（fenixd.log:5440-5441），10:27:13.678Z 第二轮同因升级握手认可该豁免（log:5614），43ms 后 10:27:13.721Z 白化门禁（escalation.py:455 → verdict_check.py:525）以同因拒绝——豁免对场景级 env 是结构性死信。冻结阈值 2 轮（state_machine.py:287）、env 冻结唯一自动清除是 verified（pipeline.py:1337），而场景按设计不可行（cfc 相机路径 720×720 + feed 1024 原图不缩放被 API1 过滤；cfc-emulator-roundtrip.sh:54 EXPECT_MD5 拿 mp4 容器 md5 比解码后 sample.bin，永不相等），verified 永不可达。一天烧掉 8 次裁决（$7.34–7.91 口径差）、2 轮规划、3 次 admin run，spec 冻结转人工。

## 问题

1. 豁免载体错位：env 豁免存 AdminStore disposition（admin_actions.py:2271），不是 spec/STATE 字段；白化门禁读不到、场景变更失效语义无处挂靠。
2. 无第三出口：env 类失败只有「修环境」（实测走不通）或「人工豁免」（结构性死信），没有「凭 admin 诊断修订场景定义后重验」回路。
3. env 归因粒度：裁决报告一句「虚拟相机链路未送帧」与 admin 实测（帧有送、解码不出）冲突，粒度不足以支撑重设计。

## 方案

- 豁免结构化：以「场景 id+归一化失败签名」为键把豁免记入 spec 级 STATE 字段（保留时效锚点），verdict_check 白化门禁消费同一数据源——命中即在 violations 中豁免该项（保持 0-pass 不变量与 fail-closed 语义），escalation 同源消费。
- 场景修订出口：adjudication choices 新增 revise_scenario_reverify 执行器——仅允许改场景定义文件（场景文件/夹具供给层），拒绝产品代码路径；复用规划车道出修订场景，重验前从冻结集合摘除并重挂；设修订次数上限（默认 2）。
- 归因证据要求：env 归因结论须附「送帧/解码」两段证据引用，缺失时裁决降级为 inconclusive 而非 env。

## 非目标

- 不做 spec 级全面豁免（白名单化到场景+签名粒度，防白化放大）。
- 不重构升级握手时序（fix-env-exemption-exit-reachability 已定时序，本条只统一数据源）。
- 不动冻结阈值（2 轮）与 verified 唯一自动清除路径。