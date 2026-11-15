# maintree WIP 归因探测对 dsh web 会话直改主树形态结构性失明

## 背景

fenixd 主树 maintree_stray_wip_stale major 告警 2026-11-10、11-11、11-13 三度同型（4 天 3 条 admin run）：均为「用户经 dsh web 会话直改主树、编辑轮结束进程即退」的活跃工作流被按无主走宽限升级。三度处置全部零触碰 resolved，且 choice 执行时均报「清单内文件已全部不在当刻工作区改动中」＝归属者事后自行提交、WIP 自愈——升级全程是误报噪音，只烧 admin run 预算。

## 结论（当前事实）

- maintree-interactive-session 只读探测以「活进程在场」为判据；dsh web 会话的 agent 执行形态是每消息派生 `claude -p`（stream-json）、消息结束进程即退。编辑发生在前、宽限 30 分钟耗尽告警在后，告警时点编辑进程必然已退出，探测确定性零命中 → 按无主升级。**这是结构性的，不是偶发抖动。**
- 实证锚点（11-13 轮）：告警 cdf57869504a（指纹 11b187b9cf93563a，12 文件 +344 行）—— 归因零命中的同时，用户 dsh 会话（FRP 3080）16:57 起在场、17:11 编辑波落其存活窗内；DESIGN.md diff 内自述「2026-11-13 用户指令『左右侧间距减少 15px』」，归属实锤。
- 复发计数口径放大噪音：与历史告警文件清单求交非空即记一轮，跨日推进的同一工作流会稳定升级成「复发型」并要求根治——但根治选项 `untrack_stray_wip` 面向生成物类散件，对源码/文档清单执行 git rm --cached 属仓库损伤，缺第三出口。

## 增强方向（候选）

1. **归因侧**：探测补 dsh 会话形态——识别 dsh registry/会话表中对本项目活跃的 web 会话（含其近期退出 claude 子进程的编辑痕迹，如 cwd/run jsonl 时间线与会话窗求交），命中则按 session-attributed info 降级（既有 `admin.maintree_session_attribution_action` 通道零改动复用）。
2. **裁决侧**：maintree_stray_wip_stale 注册表补第三选项 `track_stray_wip`（零触碰挂跟踪项收口；2026-11-13 处置已按 suggested_choice 回填提案）。

## 证据

- admin_alerts.json：24840fa8aeeb（11-10，4 文件）、34ae21ea0362（11-11，33 文件）、cdf57869504a（11-13，12 文件）；后两轮 disposition 75fb7bc4cbbb、d3e959594ce0 的「清单陈旧」error 即自愈证明。
- 处置 run：admin-fenixd-1794564788（runs jsonl）。

## 溯源

- `spec/knowledge/domains/worktree-vc/maintree-wip-attribution.md`（归因源全集与 fail-open）
- `spec/knowledge/domains/worktree-vc/maintree-stray-wip-sweep.md`（宽限升级与复发识别）
