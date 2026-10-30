# 设计

## D1 改动点与回调形态

- core/verify_report.py `ensure_verification_report(project_root, spec_name, logger=None, pre_commit=None)`：`pre_commit` 为无参 callable；三个放行出口（现 :1143/:1160/:1202）在 `_commit_verification_report(...)` 之前以 try/except Exception 调用（异常仅 WARNING，日志通道 verify_report）。默认 None 时行为逐字等价现状——push 收口等未传回调的调用方零影响。
- core/pm_engine/verification/report_gate.py `_ensure_verification_report`(:85)：函数内延迟导入 `_render_scenario_change_section_to_report` 并以 lambda/闭包（捕获 pipeline、spec_name）注入 pre_commit；外层再兜一层 try/except 返回阻断文案不必要——渲染回调自身已兜异常，闸门放行结论只由报告闸门数据决定。
- legacy 车道语义说明：legacy.py(:408/:603) 两调用点现状**无**末尾场景段渲染（`_render_scenario_change_section_to_report` 仅由 pipeline.py:1232/:1408 调用，见 scenario_gate.py 提交器注释「pipeline._apply_bug_found / _apply_verified 内」），故回调注入对 legacy 采纳是行为扩展——其报告首次获得场景段小节（闭合 legacy 车道场景段缺失缝隙），非现状保持；回调失败仅 WARNING 的降级语义使该扩展无阻断风险。

## D2 渲染数据时点

场景段渲染来源优先级不变（`_last_scenario_diff`（冻结轮写、归属戳校验）> 重新读 scenarios.json）。两者写回均发生在验证轮开始（scenario_gate.py:296 / :547），早于采纳闸门，闸门时点渲染数据就绪。首轮（persisted 为 None 且无缓存 diff）渲染函数直接返回——闸门提交仅含报告本体，等价现状的单提交，非回归。

## D3 末尾渲染点保留为兜底

pipeline.py :1408/:1232 渲染调用不移除：闸门回调未生效的轮次（如未来新增绕过 report_gate 的采纳路径）仍由尾段渲染 + 提交器兜底闭合滞留缝隙；闸门已合并时标题幂等判定（scenario_gate.py:694）使其零成本跳过。保留双挂点是有意冗余（兜底防线），非重复实现。

## D4 不做

- 不改 `_commit_verification_report` 签名与提交消息模板（「[fenix] <spec>: verification-report 入库」单模板继续覆盖唯一提交点；区分性消息模板方案随之失去必要）。
- 不动 push 收口挂点、归档兜底、`spec_has_content` 内容认可排除（知识库红线）。
- 不做历史双提交的 rebase/回填整理——已入库历史不动。