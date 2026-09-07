## ADDED Requirements

### Requirement: 统计卡移动端去重复标题并收紧内边距
390–767px 视口下，IntroduceRow 四张统计卡（SPEC 总数 / 任务进度 / Token 消耗 / 活跃 Agent 运行）SHALL 只保留卡头标题一行（卡内自绘灰眉题隐藏），card body 内边距 SHALL 收紧为 12px 16px（桌面保持 16px 24px）。≥768px 视口 SHALL 保持双标题（黑粗卡头 + 灰眉题）与 24px 水平内边距不变。

#### Scenario: 移动端统计卡单标题
- **WHEN** 390px 视口打开概览页
- **THEN** 每张统计卡内仅出现一次「SPEC 总数」等标题文本（卡头一次，卡内灰眉题不渲染或不可见），卡 body 左右内边距为 16px

#### Scenario: PC 端双标题与边距不变
- **WHEN** 1920px 视口打开概览页
- **THEN** 四卡保持卡头黑粗标题 + 卡内灰眉题的双标题布局，body padding 为 16px 24px，与基线一致

### Requirement: 统计卡数字注释行不截断
390–767px 视口下，统计卡的数字与注释行（Token 卡「8.7亿 平均每 SPEC X」、活跃 Agent 卡数字+图例行）SHALL 允许换行展示，注释文本完整可读，SHALL NOT 因 nowrap/overflow:hidden 出现省略截断或挤压。

#### Scenario: Token 注释完整换行
- **WHEN** 390px 视口打开概览页且 Token 卡存在「平均每 SPEC」注释
- **THEN** 大数字与注释完整可见（必要时分两行），无「平均每 SPEC 4…」式截断

#### Scenario: 活跃 Agent 图例完整
- **WHEN** 390px 视口打开概览页且存在活跃运行
- **THEN** 数字与类型图例（实现/规划/评审等）完整可见，必要时换行，无图例被隐藏

### Requirement: 项目清单搜索框移动端全宽可用
390–767px 视口下，项目清单卡头 SHALL 换行分两行呈现：第一行标题，第二行搜索框与状态过滤组；搜索框 SHALL 撑满可用宽度可正常输入。≥768px 视口 SHALL 保持单行卡头布局不变。

#### Scenario: 移动端搜索框全宽
- **WHEN** 390px 视口打开概览页项目清单
- **THEN** 「搜索项目」输入框宽度撑满卡体可用宽度，可正常聚焦输入；「全部/运行中/未运行」过滤组不与标题挤压同一行

#### Scenario: PC 端卡头单行不变
- **WHEN** 1920px 视口打开概览页
- **THEN** 项目清单卡头单行呈现标题 + 搜索框（160px）+ 过滤组，与基线一致
