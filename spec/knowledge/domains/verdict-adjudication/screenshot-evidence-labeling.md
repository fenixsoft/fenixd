<!-- knowledge: capability=screenshot-evidence-labeling rev=1 sources=spec/archive/2026-09-15-add-verdict-credibility-gate -->

# 截图证据标注

场景截图落盘时的纯算法健全性判定：白屏/纯色/低对比度产出结构化标签进 evidence，judge 与下游读标签不读图。

## 现行规则

- verify_engine 在场景截图落盘时（browser.py `screenshot()` 路径）以纯算法对截图内容做健全性判定，产出结构化标签写入该场景结果的 evidence，并随 report.json 的场景 evidence 持久化（对 judge 与下游消费方可见）；判定不依赖任何 LLM/多模态能力。
- `blank_screenshot`：截图像素标准差低于阈值（如 std < 3/255）且主色占比 > 99%（纯色图，含纯白/纯黑）时，evidence 增加标签 `blank_screenshot: true` 与量化指标（std、主色占比、尺寸）。
- `low_contrast`：像素标准差处于纯色阈值之上但低于低对比度阈值（复用/对齐 skimage low contrast 判定口径）时，evidence 增加标签 `low_contrast: true` 与量化指标。
- 正常截图不产生标签：健全性指标均在阈值内时不写入任何标签，消费方以「缺标签」为正常态（向后兼容）。
- 判定失败不阻断主流程：健全性判定自身异常（图像库不可用、文件损坏）时记 warning 日志并跳过标签，截图本身照常落盘与返回；判定异常不得导致场景步骤失败。

## 溯源

- [2026-09-15 add-verdict-credibility-gate](spec/archive/2026-09-15-add-verdict-credibility-gate/) — 确立截图落盘时纯算法健全性判定（blank_screenshot/low_contrast 结构化标签+量化指标）、缺标签正常态与判定异常不阻断
