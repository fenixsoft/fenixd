# ADR-379：ProLayout 主色族 scope 按档切走双通道治理

date: 2026-11-25
status: accepted

## Context

ProLayout（@ant-design/pro-components）内部按布局分区自建 ConfigProvider scope（主内容/侧栏/顶栏，160+ 元素挂 scope class），以 settings.colorPrimary 对主色派生族（页签选中态、墨条、复选框、进度条等消费面）重播种重算。defaultSettings 恒定浅档种子不随档时，深档下这些 scope 的派生族取浅档深算法的 muddy 值，而显式 token 直达的键（colorText/背景族）已正确切深——缺陷集中在被 scope 重算的派生族。同类种子陷阱（浅档黑种子/深档白种子下 *Bg 派生族不可靠）此前已两次以局部补丁处置（Menu itemActiveBg 显式给值、.ov-radio-dark 局部深档补丁），未收口到根因。

## Decision

主色族按档切走双通道：根因层在 runtime 布局配置按档覆写 settings（深档 `colorPrimary=DSH_PRIMARY_DARK` + `navTheme='realDark'`，浅档零增键），ProLayout 布局 token 通道 top-level `colorPrimary`/`colorLink` 为双保险兜底；保险层在 theme.ts 补组件级显式 token（Tabs/Progress/Radio/Checkbox 等主色族键），把用户感知面与派生链解耦——显式键不依赖派生链，scope 重算也直达。深档反墨档（Button 字色/Checkbox 勾选符号/Radio 圆点的 `colorWhite` 族）取页面基底反相，MUST NOT 用近白。验收一律以 ProLayout 各 scope 计算变量断言为准（`--ant-color-primary`/`--ant-color-link`），不信任文档与截图；antd darkAlgorithm 对种子主色族 CSS var 一律再渲染，派生值属合法深档形态，浅档残留形态判缺陷。

## Consequences

后续 dashboard UI SPEC 凡新增主色派生族消费面，深档必须走组件级显式 token 或实测确认不消费派生（如 Segmented），不得依赖 darkAlgorithm/scope 派生；判读口径以计算变量为准，muddy 派生蓝（#6b94dc 系）与暗种子残留（#101115 系）出现即缺陷。浅档路径保持零增键逐字节不变，双通道只在深档生效；局部深档补丁（按页打补丁）路线自此退役，同类缺陷先查 scope 重算根因。
