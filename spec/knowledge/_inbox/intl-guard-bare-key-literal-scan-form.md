# intl 目录键守卫：裸键形字面量是第五扫描形态（数据结构持有的 labelId）

## 背景

i18n-zh-en 抽取轮把文案抽成目录键后，键常以字符串字面量存进数据结构
（选项词典、元组常量的 `labelId` 字段），渲染期经变量传入
`intl.formatMessage({ id: labelId })`。这类键一旦漏登记目录，渲染裸键名
（如 overview 面板显示 `overview.agentCat.repair`），而
`intlIdsRegistered.test.mjs` 既有三形态扫描（formatMessage 字面量 id /
intlText 字面量 / `label: '键形'`）全部不命中——键不在调用点字面量位置。

## 结论

- `core/dashboard/static/tests/intlIdsRegistered.test.mjs` 现含五种扫描
  形态：① `formatMessage({id:'…'})` 字面量；② `intlText('…')`；
  ③ `label: '键形'`；④ 动态拼键 `` `prefix.${v}` `` 断言目录存在同前缀族；
  ⑤ 裸键形字符串字面量 `'x.y.z'`（≥3 段点分、小写起首段）
  `'([a-z][a-z0-9]*(?:\.[a-zA-Z][\w-]*){2,})'`，同样要求 ∈ zh 目录键集。
- 形态 ⑤ 是数据结构持有键的唯一静态防线；实测全仓（排除 locales）仅 11
  处命中且全为真漏登记，无误报噪声；偶发业务值撞键形走 ALLOWLIST 豁免。
- labelId 经 `formatMessage({id: 变量})` 渲染的组件（IntroduceRow
  AGENT_CATS、LlmProviderPanel PRICE_FIELDS 等）新增条目时，目录键必须
  同批登记 zh-CN.ts 与 en-US.ts；zh 目录是回退底座，缺 zh 键 = 键名直出。

## 证据

- 用户报告英文档 overview 面板渲染 `overview.agentCat.repair`；
  `core/dashboard/static/src/pages/overview/components/IntroduceRow.tsx:157-164`
  AGENT_CATS 七键与
  `src/pages/settings/components/LlmProviderPanel.tsx:54-57` PRICE_FIELDS
  四键均未登记（前轮 `579978bce` 只补了 agentCat.other + segmentTooltip）。
- zh 原文逐字恢复自抽取前基线 `ecb9470f6`（实现/规划/评审/验证/测试/
  修复/运维；输入/输出/缓存读/缓存写）。
- 修复提交 `795654fb6`；守卫 1 pass，前端 npm test 585/585；真机 en 档
  `Input($/1M tokens)/Output/Cache read/Cache write`、zh 档
  `输入/输出/缓存读/缓存写`，无裸键残留。
- overview 图例（形态 ⑤ 的第一处消费点）仅在存在活跃 agent run 时渲染
  （value>0 过滤），空闲期无法现场目视，验证以 settings 价格行常驻渲染面
  + dist bundle 双语键存在性代替。
