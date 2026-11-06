# overview 台账对齐 v2 + Bento 圆角固定 12px（2026-11-06 用户指令）

## 结论（当前生效规则）

1. **overview 项目清单=台账表格磁贴**：原版 overview 页项目清单由 ProjectCards
   （antd List 卡片墙）改为 ProjectTable（`pages/overview/components/ProjectTable.tsx`），
   呈现复制 v2 overview 台账磁贴两形态（桌面=表格、移动=堆叠项目卡）。
   **行为契约不随视觉切换**：乐观删除 + 侧边栏菜单同步（onProjectRemoved/
   onProjectSettle）、在飞 pending 记账、错误态/exists=false 语义（不可读行数据列
   渲染「—」）、跳转**本产**项目页 `/projects/:name`（不跳 /v2/）。
2. **跨域样式纪律=镜像不引用**：DESIGN.md 例外域条款钉死 v2 主题单源域外不得
   引用，故 overview 侧消费 v2 视觉的方式是**复制组件 + 镜像色值**（`OV_*` 常量 +
   global.less `.ov-*` 规则，注释标注镜像源「两处同改」，同 v2.less↔theme.tsx
   镜像纪律先例），不 import `@/pages/v2/*`；守卫测试钉死禁跨域 import。
3. **Bento 磁贴圆角固定 12px（DESIGN.md 通用条款）**：2026-11-06 用户指令自 16
   改 12 全站统一——v2 域（theme.tsx `V2_TILE_RADIUS`/v2.less）与 overview 镜像
   （global.less `.ov-bento`/统计卡豁免规则）四处同值；胶囊 999 与一般域 antd
   控件圆角 6/4/8 条款不受影响。守卫测试钉值。
4. **运行态筛选形态**：overview 台账的 全部/运行中/未运行 用 antd Radio 并排
   按钮组（原版样式），激活项黑底白字走 `.ov-bento .ant-radio-button-wrapper-checked`
   覆写；独立胶囊形态（.ov-chip）已撤退且守卫禁回潮。v2 域自身筛选仍为
   `.v2-chip` 胶囊（其域内形态不变）。
5. **表格数字列居中**：SPEC 数/问题阻塞/活跃运行 三列 `align: 'center'`（用户指令）。
6. **overview 移动端对齐 v2 概览**：统计卡行网格自 inline 样式迁 global.less
   （inline 会挡媒体查询），<768px 换 2×2（minmax(0,1fr)，gap 12——minmax(0,1fr)
   钳掉 1fr 隐式 auto 下限防长内容撑破，v2 同款）；统计卡 body 内边距 14px 16px
   （对齐 v2 移动磁贴，取代原 12px 16px 契约）；项目清单移动形态=堆叠项目卡
   （v2 原型无筛选行，移动端不渲染 Radio 组）。

## 追加指令（同日）：projects 桌面 SPEC 表格对齐 v2（antd Table 功能保留）

- **重绘非替换**（用户明示约束）：`pages/projects/list.tsx` DevTab 桌面表格
  保留 antd Table 全部功能（表头排序/分页 20+换页大小/树形展开/信息子行/
  悬浮 Why 与验证结论 Popover/优先级编辑/行选中底），仅重绘边框与行内容呈现。
- **表格边框**：Table 包 `.ov-bento` > `.ov-bento-table`（白磁贴发丝边 + 透明
  表头 + 发丝线行分隔 + 首列缩进，复用 overview 镜像 CSS，消费面注释已改
  双页共享）；优先级列表头补 nowrap（6% 定宽三字头折行）。
- **行内容 v2 形态**：状态=语义胶囊（原色点+文字）、模式=胶囊 快速(warning)/
  标准(muted)（移动卡片与详情页仍走 ModeTag 单源）、名称=dense 形态（13.5px
  半粗深色单行省略，悬浮 Why/键盘跳转不变；移动卡片保持链接蓝 16px）、
  创建时间=等宽三阶灰（精度保持完整时间戳）、任务进度=阶段名+「计数 · 百分比」
  同行在条上方（镜像 v2 PhaseProgressCell 版式；run 线索/验证·门禁 current 行
  全保留）、验证=胶囊（异常红/进行中蓝/完毕灰/未执行灰，悬浮结论不变）、
  耗时=右对齐等宽。**进度条配色不走 v2 ramp**：progressPhase.ts 阶段 ramp 是
  DESIGN.md 登记的数据编码色豁免（底轨「空条可辨」语义），保留原函数。
- **操作列**（用户指令）：「文档」并入菜单首项（dashboard-spec-table「文档
  恒可见」契约的入口位随指令迁移），触发器改三点图标（与 overview 台账同款），
  菜单其余项仍由 onMenu 单点承载；行内容其余两处（移动卡片）不变。
- **过滤 Radio 组对齐**（用户指令）：projects 类型过滤/归档切换两组 Radio 挂
  `.ov-radio-dark` 覆写类（激活黑底白字，与 overview 运行态筛选同款）；该
  覆写类自 `.ov-bento` 作用域收敛为独立单源类（overview 同步改挂）。
- **DESIGN.md 两条款**（用户指令即定稿事件）：①通用条款「Bento 磁贴圆角固定
  12px」（见上）；②一般域「Radio 按钮组激活态固定黑底白字」（单源
  `.ov-radio-dark`，现存消费面 overview 运行态 + projects 两过滤组）。
- 守卫：pageChrome.test.mjs 增 projects 表格磁贴/功能保留/行形态挂点/操作列
  三点+文档首项/`.ov-radio-dark` 单源与消费断言。



## 追加指令（同日）：spec 详情页 Bento 化（内容保持原版）

- **顶栈五卡吃 `.spec-bento-card` 皮肤**（项目信息/任务清单/质量门禁/验证进度/
  验证结论；global.less 单源覆写类，同特异性靠后置覆写页级去边框/去阴影规则），
  内容与交互零改动；**页签区卡不入 bento**（同日二次指令：tab 菜单避免卡套卡）。
- **任务清单行渲染改 v2 形态**（镜像 v2 TaskCard）：分组行=三阶灰摘要
  「标题 · done/total」；条目行=完成蓝底勾选块（`.ov-task-check`，镜像
  .v2-task-check）/未完成空心圆 + mono 编号（链接蓝）/mono 描述 + 发丝线行分隔
  （`.ov-mono` 镜像 .v2-mono）。run 线索/空态 testid（run-progress-hint 等）
  原样保留；v2 的 8 行折叠渐进披露**未采纳**（内容保持原版全显）。
- **时间轴节点=独立磁贴**（SpecTimeline cardBox 改 Bento 形态：发丝边 + 12
  圆角 + 软阴影 + 纯白底）；urgent（失败 run/门禁拒绝）警示描边与红软底保留
  ——数据语义色不随视觉换轨。任务进度列计数「xx/xx · 百分比」与左侧阶段名同款
  （12px 三阶灰常规字重，2026-11-06 用户指令；不走 v2 深色半粗形态）。**页签区包裹卡卡体 padding 归零**（`.spec-detail-card
  > .ant-card-body { padding: 0 }`）：tab 菜单退出 bento 后卡体隐形但默认 24px
  内边距仍使页签内容比上方 bento 卡左右各多缩进一圈（隐形包裹卡的内边距在
  「去边框」后仍存在，对齐问题查卡体不查边框）；窄屏 12px 收紧规则特异性更高
  不受波及。
- **质量门禁行渲染对齐任务清单**（同日追加指令）：勾选块/空心方框指示器 +
  发丝线行分隔 + 13px 文本块；gateTextColor（failed 红/pending·unknown 灰）、
  状态后缀、detail 文案数据语义保留；antd Checkbox 在本页退役（import 移除）。
  未完成指示器经用户指令定为**空心方框**（`.ov-task-empty`，15×15 radius 4 与
  勾选块同几何）——v2 TaskCard 原形为空心圆，本页系用户指令偏离镜像源，
  勿「对齐」回圆。
- **DESIGN.md 一般域新增「页面内容区间距」条款**：左右 15px（dshLayoutToken
  单源）+ 顶呼吸带 16px（页级标记类 :has() 作用 ant-layout-content，现存
  overview-page / spec-detail-page 两页；embed 行壳位档豁免归零、下游 24px）。
  spec-detail-page 标记类落 detail.tsx 根包装 div。
- 守卫：五卡计数/页签区退出/标记类/呼吸带三连/时间轴磁贴/镜像纪律断言。

## 追加指令（同日）：配置页全量卡片 Bento 边框

- **settings 页所有 `.ant-card.ant-card-bordered` 挂 Bento 边框三件套**（软阴影 +
  **圆角 10px + 加深边框 #d7d7d7**——同日二次指令：浅灰卡底 #f6f6f6 上
  #eef2f7 发丝线不可辨，边框不可见即失效；global.less 单源规则）；浅灰卡底条款
  （#f6f6f6/#efefef）不受影响——只接管边框。**灰底准例已登记 DESIGN.md 通用
  条款**（仅此一页，MUST NOT 推广至白底磁贴页）。**覆写位置纪律**：规则必须
  后置于同特异性的直角化规则（2026-11-04「圆角边框去掉」border-radius: 0）
  之后，守卫测试钉住先后顺序；卡头随卡根圆角同形（10px 10px 0 0）。

## 追加指令（同日）：指挥中心三页签卡片框 Bento 化

- **五类卡片框改 Bento 形态**（org 屏 LaneCard 车道卡 + 产品团队卡、pipeline 屏
  五列泳道容器 + 泳道 SPEC 卡、台账屏 KPI 条主框）：发丝边 #eef2f7 + 12 圆角 +
  软阴影。单源 `pages/command-center/shared.ts` 新增 `CARD_FRAME_BORDER/
  CARD_FRAME_SHADOW`（镜像 v2 theme.tsx，两处同改）；本页白底磁贴，不适用
  settings 灰底准例。
- **PANEL_BORDER 降级为非框用途**：sparkline 空点填充（OrgGrid）、流水线列头
  分隔线（PipelineBoard）保留原 0.10 档描边；连接线 LINK_STROKE（黑 0.2 alpha）
  仍比卡框深一档，白底可读。KPI 加载/错误占位框（ExecutionLedger 63/85）未动
  ——瞬态占位非卡片，且知识契约即「占位框平铺」。
- 内部元素不随框换肤：图标徽章（AVATAR_BORDER）、dashed 待命格（REST_BORDER）、
  metric 分隔线均为框内结构。

## 改动面

- 新 `pages/overview/components/ProjectTable.tsx`；删 `ProjectCards.tsx`；
  `overview/index.tsx` 换组件（props 契约不变）；
- `global.less`：统计卡豁免规则换 Bento 皮肤（#eef2f7 发丝线 + 12 圆角 + 软阴影）、
  `.ov-*` 镜像规则族、移动端密度规则更新、`.overview-project-card` 旧规则删除；
- `pages/v2/theme.tsx` `V2_TILE_RADIUS=12` + `v2.less` 镜像；
- `DESIGN.md`：通用条款新增「Bento 磁贴圆角固定 12px」，v2 例外域偏离清单两处
  radius 值随改（用户指令即定稿事件，修正案程序回写）；
- 守卫：`tests/pageChrome.test.mjs`（边框皮肤/网格迁移/台账磁贴/12px 同值/
  Radio 黑底/数字列居中/禁跨域 import/ProjectCards 勿回潮）。

## 陷阱登记

- node:test 无法 import `.tsx`（JSX 不能被 node 原生类型剥离）——v2 常量钉值
  测试走源码正则（v2TitleBarGuard 同习语），不要 import theme.tsx。
- PageContainer 页级 `box-shadow: none` 规则会打到统计卡：Bento 软阴影必须挂在
  高特异性豁免规则（1 id + 3 类）上覆写，且置于去阴影规则之后。
- v2 筛选胶囊（.v2-chip）与 overview 筛选钮（Radio 黑底）自此**形态分叉**：
  用户指令仅撤 overview 侧胶囊，v2 域不动。
