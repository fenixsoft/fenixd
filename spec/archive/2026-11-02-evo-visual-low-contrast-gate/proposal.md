# 提案：visual-low-contrast-gate

## 问题

视觉健全性门的低对比判定用固定阈值（LOW_CONTRAST_STD_UPPER=0.08，core/verify_engine/screenshot_lab.py:32）无法区分「真空白渲染失败」与「合法低对比画面」：大屏/空态类页面天然 pixel_std 在 0.06-0.094 区间贴近阈值，真实渲染被误判 low_contrast。家族已三例：

1. 10-14 add-dashboard-embed-mode：3 场景 low_contrast（pixel_std 0.063-0.080）判 env，合并人工豁免。
2. 10-25 add-spec-topology-bigscreen：空状态场景 0.0773 触发洗白门禁＋env blocked，烧 admin run 425.5s/67 轮（fenixd.log:541-544）。
3. 10-26 improve-spec-topology-pipeline-view：两场景 0.079968/0.067101 被拒，级二豁免握手首战即停车（fenixd.log:1948），烧 admin run 486.6s/60 轮＋悬置 53 分 28 秒，管理员人工像素探针 13 张取证放行（页面天然 std 0.0866-0.0941）。

[2026-10-26#可改进#5] 已提同族三条建议、零落地（git log --since=2026-10-25 -- screenshot_lab.py visual_diff.py 为空）。结构性恶化点：首跑被拒→基线永不自然固化→warning 常驻→每 env 轮必触发豁免握手，人工取证成本随大屏 spec 数量线性增长。

## 目标

1. 场景感知阈值：场景名含 empty/zero-state/placeholder 或声明低对比（场景 id 含 low-contrast/low_contrast 保留标记）的场景使用放宽上限，且放宽覆盖全部带场景上下文的判定调用侧（基线防污染门与截图标注路径），其余场景默认不变。
2. 门内收敛复核：首跑污染门命中先做一次延时重截复测，收敛（复测通过）则按正常流程固化/放行，仍污染才 baseline_rejected。
3. 证据自动落盘：污染门命中分支把当轮截图复制到 .fenix/verify-evidence/<spec>/，免人工重跑探针取证。

## 非目标

- 不动级二豁免握手与 env 豁免处置语义（fail-closed 保留）。
- 不改洗白门禁与基线顺延规则。
- 不做「与基线模板相对差异」判定（首跑无基线、无参照物，由目标 2 的收敛复核替代其意图）。