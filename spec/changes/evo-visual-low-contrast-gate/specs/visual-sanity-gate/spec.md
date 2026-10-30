# 能力：visual-sanity-gate

## R1 场景感知阈值

low_contrast 判定（core/verify_engine/screenshot_lab.py classify_screenshot，:138-145）支持按场景感知的上限：场景名含 empty/zero-state/placeholder 子串（大小写不敏感）或场景声明低对比基线模板时，使用放宽上限（新常量，缺省值以实测家族样本为参照，如 0.05-0.08 段取 0.095）；「缺标签=正常态」契约与既缺省 0.08 行为对普通场景不变。

## R2 门内收敛复核

基线防污染门（core/verify_engine/visual_diff.py:241-262）早返回 baseline_rejected 前：复用 _settle（:162-169）等待后对同场景延时重截一次并复测 classify；复测通过则按正常流程继续固化/放行，复测仍污染才 baseline_rejected（每场景每轮至多一次重截，防死循环）。

## R3 证据自动落盘

污染门命中分支把当轮 current 截图复制到 .fenix/verify-evidence/<spec>/（spec_name 已在手，visual_diff.py:73），命名含场景名与轮次；与 evo-verify-evidence-tiered-retention 的分级入库共存，不删除既有留存。