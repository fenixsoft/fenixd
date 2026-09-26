# 设计：reduce-stale-code-selfheal-noise

## 现状与挂载点（均已核实存在）

- 缺省常量：core/config.py:1488 STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT = 120；读取入口 core/config.py:1548 get_stale_code_selfheal_config（键读取 :1572/:1581），docstring :1552 起。
- 自愈触发：fenixd.py:1735 _maybe_stale_selfheal_tick（主循环 :768 挂载，1 秒粒度；空闲累计与判定 :1958-1975；touch restart_request :1977-1982）。
- 告警写入块：fenixd.py:1192-1216（kind @:1194、severity @:1197、「无需人工干预」文案 @:1208-1212、自动 mark_handled @:1215-1216）；去重常量 fenixd.py:158、判定 :1177。
- 闭环锚点约束：core/admin_store.py:400 注释明确 mark_handled 仅匹配 ESCALATION（:380/:388/:444 同口径），语义不可改。

## 改动设计

### R1 缺省提额（core/config.py）

STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT 由 120 改为 600，同步 docstring。语义依据：空闲确认窗内新代码落地会重置空闲计时（fenixd.py:1958-1975），因此密集批次只在最后一批落地后连续空闲 600 秒时触发一轮重启，批次不再逐个放大；小时间隔的独立批次各得一轮重启（代码生效时效合理）。项目覆盖路径（:1572）不动。

### R2 告警降级（fenixd.py + core/admin_store.py）

- core/admin_store.py 在 :28 附近新增 info 级 kind 常量（如 INFO = info）；不改 mark_handled / pending_escalations 的 ESCALATION 锚定口径。
- fenixd.py 写入块按条件分流：selfheal enabled 且健康 → 以 info 级 kind、severity info 写入，附当日累计计数（进程内计数器即可），跳过自动 mark_handled（info 级无处理生命周期，锚点语义不受影响），文案改为 info 级自述；「无需人工干预」措辞保留。
- 分流反面：selfheal disabled、重启请求写失败、悬空超 max_dangling_seconds（core/config.py:1500）→ 维持既有 escalation 路径原样，与 evo-add-stale-code-dangling-deadline 对齐，不双重升级。
- 60 分钟去重（fenixd.py:158/:1177）对 info 级同样生效，避免 info 留痕自身刷屏。

## 兼容与风险

- admin_alerts.json 消费方（dashboard 告警列表）若只渲染 escalation 则 info 记录自然不显示——符合降噪目的；需验证列表渲染不因未知 kind 报错。
- 既有测试 test_stale_code_selfheal.py / test_stale_selfheal_idle.py 可能锚定缺省 120 与 escalation 断言，需同步更新（见 tasks 3.x）。