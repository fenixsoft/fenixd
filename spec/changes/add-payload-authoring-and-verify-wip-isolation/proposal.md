# Proposal: add-payload-authoring-and-verify-wip-isolation

## Why

2026-11-12 web-browser-client SPEC 修订重验事故暴露了 fenix 裁决自动化链的一组结构性缺口（同族前科三次：2026-10-31 fix-admin-choice-payload-and-scenario-pairing 修 200 字截断通道；2026-10-30 / 2026-11-03 register-revise-scenario-choice-on-intervention-signals 修桶注册可达性；本次为第三次变体）：

1. **载荷作者缺位（核心）**：`revise_scenario_reverify` 是注册表唯一 `requires_payload=True` 选项。arbiter 完成了调查与推荐，auto-exec 引擎四判据全过，但载荷门（core/admin_auto_exec.py:403-408）按设计前置跳过——自动通道没有能产出载荷（完整修订场景集 JSON）的作者；策略又写死"转人工"，不再派发任何可起草载荷的 agent run。结果每轮精确停在"等一个不存在岗位上的作者"，最终由带外 agent 直调执行器收口。
2. **人工门无工具**：面板告警选择题的 note 输入框即载荷通道（useAlertAdjudication.tsx:72 → alert_routes.py:565），但无预填、无 schema 提示、无校验、无前置指引。载荷实测 133,979 字节，靠报错文本传达 JSON 契约不构成可用接口。
3. **前置不可见**：执行器门序为 载荷解析(②)→冻结前置(④)（FREEZE_ERROR_PREFIX 前缀 spec 须先 unfreeze_spec）。人工要连踩两个错才能凑齐全部前置，面板对冻结/预算/白名单前置零呈现。
4. **跳过循环无闭锁**：载荷门每分钟重复完整评估并刷同文 INFO 日志（实测 09:07–09:11 五条），无状态迁移、无责任指派。
5. **验证构建被主树 WIP 打断（同日第二事故）**：验证轮 prepare/场景命令直接在共享主树执行，交互会话未提交 WIP（boot-recovery 半成品，StreamService.kt requestRecovery/recoveryPass 未解析引用）致 gradle BUILD FAILED，全轮 fail。框架把 WIP 归因降级 info 留痕，但 fail 轮数与 _env_block_rounds 照计，持续逼近冻结阈值——他人会话的合法并行工作演变为本 SPEC 的环境阻塞，语义错位。

## What Changes

- **G4 载荷门闩锁**：auto-exec 引擎对 requires_payload 跳过做闩锁——首跳把 skip_reason 写入告警 auto_exec 投影（徽标位已存在），后续 tick 短路不再重复评估与刷日志；告警状态变化或草稿落位时重评。
- **G1 载荷起草 run**：闩锁成立且 pending 超 grace 后，派发 Administrator 起草 run（kind=admin_payload_draft）：只调查并构造 choice_payload 草稿（完整场景集+reason+白名单夹具），落盘前过 validate_scenario_dicts / validate_scenario_revision_paths 预校验；草稿落 `.fenix/admin_payload_drafts/<alert_id>.json` 并挂告警指针。**起草 run 绝不执行修订、不消耗修订预算**；执行永远由人工批准触发（经既有 alert-resolve note 通道直达执行器既有门序）。同告警起草单飞 + 连续派发上限，失败降级为现行纯人工语义。
- **G2/G3 面板载荷编辑器与前置清单**：requires_payload 选项选中时渲染专用载荷编辑器（预填草稿或盘上现集、schema 提示、客户端 JSON 校验、空载荷拦截）；提交前展示执行前置清单（冻结态→一键解冻前置动作、修订预算余量、白名单路径提示）；草稿在位时提供"按草稿执行"入口。新增 payload-source 只读取材端点。
- **G5 验证 WIP 隔离**：验证轮启动预检主树未提交改动与验证涉及路径的重叠（排除面与 merge-back WIP gate 一致：`.fenix/` 运行时产物、`spec/changes/**` 不参与）；重叠时优先改用干净 worktree（从 HEAD 创建/复用）执行构建与场景命令，报告标注 verify_root 留痕；隔离不可行则本轮跳过——不计入验证失败轮与 _env_block_rounds，写 info 留痕，绝不据此冻结。主树干净时行为与现状完全一致（零回归）。

## Capabilities

- **adjudication-auto-exec**（MODIFIED）：载荷门跳过闩锁语义。
- **admin-payload-drafting**（ADDED）：载荷起草 run 的触发、契约、草稿落位与批准执行边界。
- **adjudication-ui**（MODIFIED）：告警选择题交互扩展——载荷编辑器、前置清单、按草稿执行。
- **verify-wip-isolation**（ADDED）：验证轮主树 WIP 重叠预检、worktree 隔离执行与跳过不计数兜底。

## Impact

- 代码：`core/admin_auto_exec.py`（闩锁）、`core/admin_monitor.py`（起草派发）、新增草稿存取模块、`core/dashboard/routes/alert_routes.py`（payload-source 端点）、`core/dashboard/static/src/hooks/useAlertAdjudication.tsx` + `services/dashboard.ts`（编辑器/前置清单）、`core/verify_engine/`（预检与隔离执行）、`core/worktree_manager.py`（干净 worktree 供给）。
- 测试：test_admin_auto_exec_policy、test_dual_lane_adjudication、test_adjudication_choices、验证引擎族扩展 + 新增隔离用例。
- 运行时产物（非交付物）：`.fenix/admin_payload_drafts/`（gitignore）。
- 知识域：admin-ops（adjudication-auto-exec / admin-choices-contract）、verify-pipeline、verdict-adjudication 域页随收尾回填素材投递 `spec/knowledge/_inbox/`。
- 兼容性：自动通道对 requires_payload 选项"永不直接执行"的保守原则不变；人工路径契约（note 即载荷）不变；主树干净时验证行为零变化。
