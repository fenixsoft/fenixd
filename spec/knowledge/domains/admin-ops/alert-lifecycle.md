<!-- knowledge: capability=alert-lifecycle rev=1 sources=spec/archive/2026-09-06-add-alert-auto-resolve -->

# 告警生命周期自动闭环

升级类告警与底层触发条件的状态联动：条件解除自动解决、存量回填、视图分组。

## 现行规则

- 升级类告警写入时附带结构化 `trigger` 字段（经 `alert_lifecycle.attach_trigger` 埋点）：包含可判定闭环的类型标识与关联对象（spec 名、计数阈值、报告路径），足以独立判断「该条件当前是否已解除」，闭环判定不解析自然语言 description。
- 条件解除时自动闭环：`handled=True`、`handled_at` 为解除时刻、`handled_by="auto-resolve"`、`resolve_note` 记录解除依据（如「spec x 已到达终态 pushed」）；自动闭环不覆盖已存在的人工处理记录（handled_by 非 auto-resolve 的记录内容与时间戳保持不变）。
- 闭环扫描内联于既有周期巡检执行，不引入独立线程或定时器；单轮扫描复杂度为 O(未闭环告警数)，全部已闭环时零 IO 开销（不写回 admin_alerts.json，mtime 不变）。
- 存量回填：daemon 启动时（或闭环机制首次生效时）对 handled=False 的历史告警执行一次回填判定——关联 spec 已到达终态或已离开 blocked 的自动闭环（同样带 auto-resolve 标注与回填来源说明）；无法关联 spec 或条件无法判定的保持原状，保留「历史遗留」语义。
- 视图分组：管理员视图告警列表按处理状态区分——待处理（handled=False）默认置顶显著展示；已自动解决与已人工处理折叠或分区展示，可展开查看 resolve_note 与 handled_at，不与待处理项混排。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：告警写入时埋点结构化 trigger 字段，周期扫描按闭环判定自动解决；已解决告警折叠展示
- 2026-09-06 add-alert-auto-resolve — 固化闭环契约：trigger 结构化埋点、auto-resolve 标注与人工记录保护、巡检内联零开销扫描、启动回填与视图三分组
