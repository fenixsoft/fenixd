# spec: screenshot-evidence-labeling（截图健全性算法标签）

## ADDED Requirements

### Requirement: 截图落盘时算法判定健全性

verify_engine 在场景截图落盘时（browser.py `screenshot()` 路径），以纯算法对截图内容做健全性判定，产出结构化标签写入该场景结果的 evidence。判定必须不依赖任何 LLM/多模态能力。

#### Scenario: 纯白（或纯色）截图产出 blank_screenshot 标签

- **WHEN** 截图的像素标准差低于阈值（如 std < 3/255）且主色占比 > 99%（纯色图，含纯白/纯黑）
- **THEN** 场景 evidence 增加标签 `blank_screenshot: true` 与量化指标（std、主色占比、尺寸）
- **AND** 标签随 report.json 的场景 evidence 持久化，对 judge 与下游消费方可见

#### Scenario: 低对比度截图产出 low_contrast 标签

- **WHEN** 截图像素标准差处于纯色阈值之上但低于低对比度阈值（复用/对齐 skimage low contrast 判定口径）
- **THEN** 场景 evidence 增加标签 `low_contrast: true` 与量化指标

#### Scenario: 正常截图不产生标签

- **WHEN** 截图健全性指标均在阈值内
- **THEN** 不写入任何标签（无标签 = 正常，消费方以「缺标签」为正常态，保持向后兼容）

#### Scenario: 判定失败不阻断截图主流程

- **WHEN** 健全性判定自身异常（如图像库不可用、文件损坏）
- **THEN** 记 warning 日志并跳过标签，截图本身照常落盘与返回
- **AND** 判定异常不得导致场景步骤失败
