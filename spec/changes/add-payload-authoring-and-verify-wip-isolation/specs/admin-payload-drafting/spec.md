# Spec Delta: admin-payload-drafting

## ADDED Requirements

### Requirement: 载荷起草 run 触发与幂等

对推荐 choice 经注册表解析 `requires_payload=True` 且 auto-exec 载荷门闩锁成立（adjudication-auto-exec 能力）的 pending 告警，系统 MUST 在闩锁持续超过 grace 窗（复用 auto-exec grace 配置，单源 core/config.py）后派发一个 Administrator **载荷起草 run**（run kind=`admin_payload_draft`）。派发 MUST 幂等：同一告警同时至多存在 1 个在跑起草 run；同一告警连续起草派发次数达上限（缺省 2，config 单源可调）后 MUST 停止派发并保持纯人工等待。起草派发 MUST NOT 改变告警的 pending 状态，MUST NOT 触发 spec 状态机的任何跃迁。

#### Scenario: 闩锁超窗派发起草 run
- **WHEN** 一条 verify_env_blocked 告警的推荐 revise_scenario_reverify 载荷门闩锁成立且超过 grace 窗，且该告警此前无在跑起草 run、连续派发计数为 0
- **THEN** 系统派发一个 kind=admin_payload_draft 的 Administrator run，输入含告警上下文（spec 名、signal_type、judge 归因与证据引用、推荐 choice id、修订预算余量），告警保持 pending

#### Scenario: 起草单飞与上限
- **WHEN** 同一告警已有一个在跑起草 run 时闩锁条件再次满足；或同告警连续起草 run 已达 2 次且均未产出合法草稿
- **THEN** 前者不重复派发（复用在跑 run 的产物等待落位）；后者停止派发，告警投影标注起草失败转纯人工，日志留痕

### Requirement: 起草 run 契约——只起草不执行

起草 run 的职责 MUST 限于：调查告警上下文、构造 `choice_payload` 草稿 JSON（形态 `{"scenarios": [...完整场景集...], "reason": "...", "fixture_files": [{"path", "content"}...]}`）、将草稿落位。起草 run MUST NOT 调用任何 choice 执行器（含 `_exec_revise_scenario_reverify`）、MUST NOT 消耗场景修订预算、MUST NOT 写场景集成对文件与夹具供给文件。草稿落位前 MUST 通过与执行器同源的预校验（`validate_scenario_dicts` 结构校验 + `validate_scenario_revision_paths` 白名单校验，core/verify_engine/scenarios.py:1946 与 core/dashboard/data/adjudication_choices.py）；预校验不过 MUST NOT 落位草稿，run 以失败收工并留痕校验错误。草稿 MUST 落 `.fenix/admin_payload_drafts/<alert_id>.json`（gitignore 运行时产物）并在告警记录挂 draft 指针（含落位时间与校验通过标记）。告警不存在或已被处置时起草 run MUST 安全退出不落盘。

#### Scenario: 合法草稿落位挂指针
- **WHEN** 起草 run 产出的草稿通过 validate_scenario_dicts（错误为空）与 validate_scenario_revision_paths（全部路径在白名单目录）
- **THEN** 草稿写入 .fenix/admin_payload_drafts/<alert_id>.json，告警记录附 draft 指针与校验通过标记，告警保持 pending，修订预算计数不变

#### Scenario: 非法草稿不落位
- **WHEN** 起草 run 产出的草稿含白名单外路径或结构错误（如场景缺 id/steps）
- **THEN** 草稿不落盘、告警无 draft 指针，run 结果留校验错误明细，该告警连续起草计数 +1

#### Scenario: 起草 run 越界被执行契约拦截
- **WHEN** 起草 run 的结果记录携带了任何执行类动作痕迹（如调用执行器、写 test_scenarios.json）
- **THEN** 结果门判该 run 失败并留痕越界明细，草稿与告警状态不受污染（复用 maintenance_runs 处置产物硬门的 fail-closed 先例形态）

### Requirement: 批准执行走既有门序且不自动重试

草稿在位的告警 MUST 支持人工批准执行：经既有 alert-resolve 通道将草稿载荷作为 note 提交，执行器既有门序（载荷解析、终态守卫、冻结前置、修订预算、白名单、结构预校验、原子写、成对覆盖、状态落位、重派）原样生效——本能力 MUST NOT 为批准执行新增第二套执行逻辑或旁路任何既有门。执行器返回 not-ok（如预算耗尽、冻结未解）时，草稿 MUST 保留、告警保持未处理并回显执行错误；系统 MUST NOT 对失败草稿自动重试执行。人工可在提交前编辑草稿内容（adjudication-ui 能力的编辑器），编辑后的内容以人工提交版本为准。

#### Scenario: 批准执行直达既有门序
- **WHEN** 用户在面板对草稿在位的告警点击"按草稿执行"
- **THEN** alert-resolve 以草稿载荷为 note 调用既有执行通道，成功时修订预算计数 +1、成对文件覆盖、spec 重入验证重派；全程无新增执行代码路径

#### Scenario: 执行失败草稿保留不重试
- **WHEN** 批准执行被执行器拒绝（如 spec 处于用户指令冻结且前置解冻未做，或修订预算已耗尽）
- **THEN** 草稿保留在盘、告警保持未处理、错误信息回显面板；系统不自动重发该载荷，前置条件满足后人工可再次提交

### Requirement: 起草失败降级纯人工语义

起草 run 派发失败（harness 不可达、provider 异常等）或连续派发超限时，系统 MUST 降级为现行纯人工语义：告警保持 pending、skip_reason 投影可见、日志留痕。降级 MUST NOT 触发告警升级（如冻结、转 arbiter）、MUST NOT 阻塞其他告警的 auto-exec 评估与其他车道。

#### Scenario: harness 不可达降级
- **WHEN** 起草 run 派发时 harness spawn 失败
- **THEN** 该告警本次派发放弃、连续计数 +1，告警保持 pending 且其余告警的 auto-exec 判定与本 SPEC 验证车道均不受影响
