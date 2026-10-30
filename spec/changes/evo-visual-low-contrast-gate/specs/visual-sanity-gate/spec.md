# 能力：visual-sanity-gate

## R1 场景感知阈值

low_contrast 判定（core/verify_engine/screenshot_lab.py classify_screenshot，判定分支 :140-148）支持按场景感知的上限：场景名含 empty/zero-state/placeholder/low-contrast/low_contrast 子串（大小写不敏感）时使用放宽上限（新常量 LOW_CONTRAST_STD_UPPER_RELAXED，缺省 0.095，参照实测家族样本 pixel_std 0.063-0.0941）；「场景声明低对比」以场景 id 含 low-contrast/low_contrast 保留标记实现（复用同一子串匹配助手，不新增场景 schema 字段——ScenarioEntry 为固定 __slots__，core/verify_scenarios.py:113-165）。放宽阈值 MUST 覆盖全部带场景上下文的 classify_screenshot 调用侧：visual_diff 基线防污染门（visual_diff.py:243，scenario_id 在手）与 browser.screenshot 截图标注路径（core/verify_engine/browser.py:1847，name 参数即场景名）——后者产出的 screenshot_labels 经 web_runner.py:484 写入场景、由 verdict_check.py:1174-1180（归因分级）与 :1780（缓存豁免）消费，是「low_contrast 判 env」链路的标签源头，只放宽污染门一侧则引用家族沿标注侧复发。无场景上下文的调用缺省 0.08 行为不变，「缺标签=正常态」契约不变。

## R2 门内收敛复核

基线防污染门（core/verify_engine/visual_diff.py:241-262）早返回 baseline_rejected 前：复用 _settle（:162-169）等待后对同场景延时重截一次并复测 classify（复测件先落盘到轮次命名文件 `{scenario_id}_current_r{n}.png`，对齐既有重拍纪律 code-review 4693d3ce3731）；复测通过入选时 MUST 先把复测截图回写标准路径 current_path 再进入正常流程——基线固化从 current_path 复制（visual_diff.py:334），不回写会把污染首图固化为基线，与本门目的相反；复测通过后继续走既有门序（判定失败防护 :273、基线固化门 :302），复测仍污染才 baseline_rejected（每场景每轮至多一次重截，防死循环）。

## R3 证据自动落盘

污染门命中分支把当轮截图复制到 .fenix/verify-evidence/<spec>/（spec_name 已在手，visual_diff.py:73），命名含场景名与轮次；发生门内复测（R2）时首截与复测件均落盘（复测件命名带 r{n} 后缀，与既有重拍命名同型），免人工重跑探针即可核对两态；与 evo-verify-evidence-tiered-retention 的分级入库共存（落位目录即该契约缺省 .fenix/verify-evidence/<spec>/，core/verify_contract.py:158-163），不删除既有留存。