# 设计：reduce-stale-code-selfheal-noise

## 现状与挂载点（均已核实存在）

- 缺省常量：core/config.py:1488 STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT = 120；读取入口 core/config.py:1548 get_stale_code_selfheal_config（键读取 :1572/:1581），docstring :1552 起。
- 自愈触发：fenixd.py:1735 _maybe_stale_selfheal_tick（主循环 :768 挂载，1 秒粒度；空闲累计与判定 :1958-1975；touch restart_request :1977-1982）。
- 告警写入块：fenixd.py:1192-1216（kind @:1194、severity @:1197、「无需人工干预」文案 @:1208-1212、自动 mark_handled @:1215-1216）；去重常量 fenixd.py:158、判定 :1177。
- 闭环锚点约束：core/admin_store.py:400 注释明确 mark_handled 仅匹配 ESCALATION（:380/:388/:444 同口径），语义不可改。

## 改动设计

### R1 缺省提额（core/config.py）

STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT 由 120 改为 600，同步 docstring。语义依据（评审修正 2026-09-27：原稿「空闲确认窗内新代码落地会重置空闲计时」与实测不符——`_stale_idle_since` 全部复位点（fenixd.py:348/:1762/:1851/:1892/:1927/:1958/:1984）均由非空闲信号（活跃 run / 在飞评审 run / admin 在途，fenixd.py:1956-1959）或陈旧状态解除（:1762）触发，无一是「新代码落地」）：合批效果来自确认窗本身的延迟收编——重启加载的是触盘时点的全部代码，600 秒窗内相继落地的多批代码由同一轮重启一次收编；而触发重启需一段无活跃 run / admin 在途的连续空闲达 600 秒，开发日 120-600 秒的短间隙不再各自成轮，批次不再被逐个放大。小时间隔（>600 秒连续空闲）的独立批次各得一轮重启（代码生效时效合理）。项目覆盖路径（:1572）与热更新语义不动。

### R2 告警降级（fenixd.py + core/admin_store.py）

- core/admin_store.py 在 :28 附近新增 info 级 kind 常量（如 INFO = info），并**同步把 INFO 加入 latest_signal 的 kind 白名单**（core/admin_store.py:542 `kind not in (SIGNAL, ESCALATION, DISPOSITION)`）——否则 info 记录对 latest_signal(None, "stale_code", …) 不可见，60 分钟去重对 info 级整体失效、高频提交下每次 daemon 轮换重启都重复成条，降噪目标落空。不改 mark_handled / unhandled / pending_escalations 的 ESCALATION 锚定口径。
- fenixd.py 写入块按条件分流。写入时点可判定的「健康」谓词 = stale_code_selfheal.enabled 且未悬空超限（_dangling_timeout_fired 未触发）；「自愈重启请求成功发出并生效」发生在写入之后的 idle_confirm 窗口末尾，不作为写入分支条件。健康 → 以 info 级 kind、severity info 写入，不调用 mark_handled（info 级无处理生命周期，锚点语义不受影响），文案改为 info 级自述；「无需人工干预」措辞保留。日计数口径：当日累计以 admin_alerts.json 中当日 signal_type=stale_code 记录数计（read_all 遍历，跨重启存活）——进程内计数器在 daemon 高频自愈重启下每次归零，撑不起「当日」语义。info 记录写入时自带 handled=true + handled_at（随 append payload 落盘，不经 mark_handled 接口），避免无处理生命周期的记录在遍历 read_all 的视图里呈现为永久未处理。
- 分流反面：selfheal disabled → 沿用既有写入块的 escalation 路径（现状即无条件 escalation，保留该分支即可）；悬空超 max_dangling_seconds（core/config.py:1500）→ 既有 _alert_dangling_timeout 升级路径原样（fenixd.py:1555，独立 signal_type=stale_code_dangling_timeout），不双重升级；重启请求写失败（fenixd.py:1984-1986 OSError 分支，现仅 logger.error）→ **新增** escalation 写入点（复用 _alert_dangling_timeout 的 append + latest_signal 去重范式，signal_type 仍取 stale_code，与 info 记录同受 60 分钟窗口互斥成条）——该升级此前不存在，「保留既有路径」不适用于此项。
- 60 分钟去重（fenixd.py:158/:1177）对 info 级同样生效，避免 info 留痕自身刷屏；前提是上一条 latest_signal 白名单同步完成。

## 兼容与风险

- admin_alerts.json 消费方按 kind 过滤（评审核实）：unhandled() 与已处理历史仅取 ESCALATION（core/dashboard/data/admin_alerts.py:21/:35-36）、SPEC 时间轴取 ESCALATION+DISPOSITION（core/dashboard/data/timeline.py:110-112）、adjudication 前端告警区仅 ESCALATION（core/dashboard/data/adjudication_choices.py:227-228）——info 记录自然不显示，符合降噪目的；实现后按 tasks 3.3 验证未知 kind 不致渲染报错。
- 缺省 120 在后端与前端各有一份硬编码副本，须与 core/config.py 同步为 600，否则设置页以 120 回填表单、用户保存即把 120 显式写入项目配置、静默覆盖新缺省：core/dashboard/data/config_admin.py:450-451（生效配置 seeds）、core/dashboard/static/src/pages/settings/components/StaleCodeSelfhealPanel.tsx:9-10（DEFAULT_IDLE_SECONDS）、core/dashboard/static/src/services/dashboard.ts:1263-1269（注释）；前端 src 改动后同步重建 dist（见 tasks 2.5）。
- 既有测试影响面（评审核实）：test_stale_code_selfheal.py 锚定 escalation 断言（:59-78/:113/:501）与缺省 120（:604-610），test_stale_selfheal_idle.py 锚定 idle 缺省与触发节奏——两者均需同步更新（见 tasks 3.x）；test_stale_selfheal_cooldown.py 的 DEFAULTS 仅含冷却五键（:186-194）、test_admin.py 陈旧告警测试以 admin_store=None 跳过写入（:2951）——不受本 SPEC 影响。