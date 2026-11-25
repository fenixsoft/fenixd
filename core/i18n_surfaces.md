# i18n 改造面盘点（add-framework-i18n-zh-en 4.4）

判据（design D5 / 知识页 locale-i18n 三层消息面单源边界）：**文本由后端组装且前端直接渲染不再加工**才进后端目录 `core/i18n.py`；前端 kind→标签映射（时间轴处置链事件标签、AGENT_LABEL、blockedPhaseMeta，见 SpecTimeline.tsx / utils/runVisual.ts）属前端目录面，MUST NOT 重复进后端目录；内部日志/落盘产物不改造。

本清单 = 本 SPEC 改造点位的键清单对账（zh 均与改造前字面量逐字一致，zh 用户零感知；en 为对照翻译）。

## base.py `_error` 键展开通道（4.3 奠基，4.4 调用点接线）

`_error(code, msg, key=..., **kw)`：传 `key` 时按请求 `Accept-Language` 解析 locale（`core.i18n.resolve_locale`）经 `t()` 展开；键不在目录时保留 msg 原文（防裸键名）。响应结构/HTTP 状态零变化。

## alert_routes.py（告警裁决动作错误面）

| 键 | zh（改造前字面量） | 点位 |
| --- | --- | --- |
| error.alert_already_handled | alert already handled（不重复执行动作） | POST adjudicate 重复动作守卫（409） |
| error.alert_not_adjudicable | 该告警不可人工裁决（signal_type={signal_type}…） | 非 choice 类信号拒绝裁决（400） |
| error.invalid_choice_id | 非法 choice_id '{choice_id}'，该信号合法选项：{legal} | choice 白名单守卫（400） |
| error.adjudication_exec_failed | 动作执行异常（告警保持未处理，可重试裁决） | 裁决动作异常兜底（500） |
| error.adjudication_not_ok | {detail}（告警保持未处理，可调整后重试） | 动作返回非 ok（400；detail 透传动作侧文本） |
| error.handled_mark_failed | 动作已执行成功，但 handled 标记写入失败… | handled 标记写失败（500） |

## code_review_routes.py（审查/修复触发与发现项人工置状态）

| 键 | zh | 点位 |
| --- | --- | --- |
| error.code_review_scope_invalid | 非法 scope（应为 full 或 window）: {value} | 触发参数守卫（400） |
| error.code_review_running | 已有审查在进行中 | 审查并发守卫（409，_coded_error 调用点 t() 展开） |
| error.code_review_backlog | 台账仍有 {count} 条 open（超过确认阈值 {threshold}）… | 全仓审查 backlog 确认门（confirm=true 引导文案） |
| error.code_review_ack_pending | 审查已受理，正在启动（文件收集/排队中），请稍候 | 触发受理确认（_json 内提示文本） |
| error.code_review_request_pending | 已有未消费的审查触发请求（请稍后重试） | 触发请求去重守卫（409） |
| error.code_review_trigger_failed | 审查触发信号写入失败 | 信号写失败（500） |
| error.code_fix_trigger_failed | 修复触发信号写入失败 | 修复触发信号写失败（500） |
| error.code_fix_request_pending | 已有未消费的修复触发请求（请稍后重试） | 修复触发请求去重守卫（409） |
| error.item_ids_not_array | item_ids 必须为字符串数组 | 批量置状态参数校验（400） |
| error.item_ids_empty | item_ids 不能为空 | 同上（400） |
| error.fix_spec_failed | 生成修复 SPEC 失败（详见服务端日志） | 发现转修复 SPEC 生成失败（500） |
| error.item_status_invalid | status 仅支持 open/ignored（人工可置状态）: {value} | 置状态词表守卫（400） |
| error.item_status_failed | 状态流转失败（详见服务端日志） | 置状态失败（500） |

## evolution_routes.py（自进化建议项三动作 + 立项参数）

| 键 | zh | 点位 |
| --- | --- | --- |
| error.evo_item_id_missing | 缺少 item_id 参数 | `_evolution_item_action` 共用守卫骨架（400；三端点同键） |
| error.evo_item_not_found | 条目不存在: {item_id} | accept/delete 条目缺失（404） |
| error.evo_doc_missing | 缺少 doc 参数（proposal\|design\|tasks\|spec） | 立项文档参数守卫（400） |
| error.evo_doc_invalid | 非法 doc 参数（应为 proposal\|design\|tasks\|spec）: {doc} | 立项文档词表守卫（400） |
| error.evo_accept_thread_failed | 后台接受任务线程启动失败，请重试 | 后台接受线程启动失败（500） |
| error.evo_start_after_invalid | start_after 非法（应为 UTC ISO8601 / manual）: {value} | 立项 start_after 解析守卫（400） |
| error.evo_no_active_accept | 该条目没有进行中或已完成的接受任务: {item_id} | accept 状态查询（404） |
| error.evo_accept_failed | 接受失败（详见服务端日志） | accept 泛化 500（helper error_key 通道） |
| error.evo_reject_failed | 拒绝失败（详见服务端日志） | reject 泛化 500 |
| error.evo_delete_failed | 删除失败（详见服务端日志） | delete 泛化 500 |

## run_routes.py（运行取消前置守卫）

| 键 | zh | 点位 |
| --- | --- | --- |
| error.cancel_request_pending | 已有进行中的取消请求，请等待受理 | 取消冲突（409，_coded_error 调用点 t() 展开） |
| error.cancel_daemon_unmanaged | 本项目 daemon 未受 supervisor 托管，取消信号不会被消费 | unmanaged 前置拒绝（409） |
| error.daemon_not_running | daemon 未运行，请先启动 daemon | daemon_down 前置拒绝（400） |
| error.cancel_write_failed | 写入取消请求失败 | 取消信号写失败（500） |

## 显式不改造面（对账留痕）

- 内部运行日志（logger.info/exception 文本）、落盘产物：操作员面，保持中文。
- `result.get("error")` 透传值（数据层组装文本）：数据层文案单源，本 SPEC 不下探（避免改造面无界扩散）；前端展示场景为 toast 透传，zh 保持现状。
- alert_routes `signal_type=signal_type or "缺失"` 的缺省词：zh 保真优先（en 请求该缺省分支显示中文「缺失」，属异常路径降级，登记为已知边界）。
- 时间轴处置链事件标签 / AGENT_LABEL / blockedPhaseMeta：前端 kind→标签映射（任务 3.5 前端目录面），不进后端目录。
