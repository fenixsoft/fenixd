// 页面 chrome 去冗余守卫（2026-11-04「内容区 40px 留白 + 包裹卡边框」治理回归守卫）。
//
// 治理内容（帮助页取证推广全菜单）：
// - PageContainer 内容区左右留白 pro-layout 默认 40px → 15（2026-11-04 用户二次
//   裁决：首版齐平 0 过紧，回撤窄边距）：theme.ts dshLayoutToken 单源（app.tsx
//   layout 配置 token 键消费），页头标题行同 token 自动对齐；<768 窄屏 12px 由
//   global.less 既有覆盖规则接管，不受影响。注意 pro-layout getLayoutDesignToken
//   的缺省回填是 `x || 40`，0 会被吞——实际生效靠其尾部
//   `...finalDesignTokens.pageContainer` 展开，值改动前须复核该合并行为。
// - PageContainer 内容区 .ant-card-bordered 统一去边框（global.less #root 前缀
//   规则）：白底页面上包裹卡边框属冗余 chrome，对齐宿主 dsh web 平铺风格。
//
// 零依赖 node:test 源码扫描（同 darkSeedBgToken.test.mjs 习语）；视觉行为由
// `npm run build` 与浏览器冒烟覆盖，本文件锁定配置单源与接线。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { dshLayoutToken } from '../src/theme.ts';

const STATIC_ROOT = join(import.meta.dirname, '..');

test('内容区左右留白单源=15px：pro-layout 缺省 40px 不得回潮', () => {
  assert.equal(dshLayoutToken.pageContainer.paddingInlinePageContainerContent, 15);
});

test('app.tsx layout 配置必须消费 dshLayoutToken（漏接线则 40px 回潮）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'app.tsx'), 'utf8');
  assert.match(text, /token:\s*dshLayoutToken/);
});

test('global.less 必须保留内容区卡片去边框规则（页级作用域，Modal/大屏例外域不受影响）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    text,
    /#root \.ant-pro-page-container \.ant-card\.ant-card-bordered \{\s*border: 0;/,
  );
});

test('概览统计卡行必须保留边框（页级去边框规则的定向豁免；组件侧 variant=outlined）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  // 豁免规则须在页级去边框规则之后（同特异性靠后置生效）
  const removalAt = less.indexOf('#root .ant-pro-page-container .ant-card.ant-card-bordered');
  const exemptAt = less.indexOf('#root .overview-intro-row .ant-card.ant-card-bordered');
  assert.ok(removalAt !== -1 && exemptAt > removalAt);
  // 2026-11-06 用户指令：边框风格对齐 v2 overview Bento 磁贴（发丝线 + 12 圆角
  // + 软阴影；圆角单源 DESIGN.md 通用条款「Bento 磁贴圆角固定 12px」，全站统一）
  assert.match(
    less,
    /#root \.overview-intro-row \.ant-card\.ant-card-bordered \{\s*border: 1px solid #eef2f7;\s*border-radius: 12px;\s*box-shadow:\s*0 1px 3px rgba\(15, 23, 42, 0\.05\),\s*0 1px 2px rgba\(15, 23, 42, 0\.03\);/,
  );
  const tsx = readFileSync(
    join(STATIC_ROOT, 'src', 'pages', 'overview', 'components', 'IntroduceRow.tsx'),
    'utf8',
  );
  assert.match(tsx, /<Card\s+variant="outlined"/);
  assert.doesNotMatch(tsx, /variant="borderless"/);
});

test('概览统计卡行网格迁 global.less（inline 样式会挡住移动端 2×2 断点规则）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  const tsx = readFileSync(
    join(STATIC_ROOT, 'src', 'pages', 'overview', 'components', 'IntroduceRow.tsx'),
    'utf8',
  );
  // 布局单源在 CSS：桌面 auto-fit 与移动 2×2（对齐 v2 概览 KPI 移动磁贴）双档齐备
  assert.match(less, /\.overview-intro-row \{\s*display: grid;\s*grid-template-columns: repeat\(auto-fit, minmax\(170px, 1fr\)\);/);
  assert.match(
    less,
    /#root :is\(\.screen-xs, \.screen-sm\) \.overview-intro-row \{\s*grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\);/,
  );
  assert.doesNotMatch(tsx, /gridTemplateColumns/);
});

test('概览项目清单=台账表格磁贴（2026-11-06 用户指令对齐 v2 台账；ProjectCards 退役）', () => {
  // ProjectCards.tsx 已删除，勿回填
  assert.equal(existsSync(join(STATIC_ROOT, 'src', 'pages', 'overview', 'components', 'ProjectCards.tsx')), false);
  const index = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'overview', 'index.tsx'), 'utf8');
  assert.match(index, /import ProjectTable from '\.\/components\/ProjectTable'/);
  assert.match(index, /<ProjectTable/);
  const tsx = readFileSync(
    join(STATIC_ROOT, 'src', 'pages', 'overview', 'components', 'ProjectTable.tsx'),
    'utf8',
  );
  // 行为契约不随视觉切换：乐观删除回调、错误态分支、跳转本产项目页
  assert.match(tsx, /onProjectRemoved\?\./);
  assert.match(tsx, /onProjectSettle\?\./);
  assert.match(tsx, /history\.push\(`\/projects\/\$\{encodeURIComponent/);
  // 样式镜像纪律：不得跨域 import v2 主题（例外域配色单源）
  assert.doesNotMatch(tsx, /from '@\/pages\/v2\//);
  assert.doesNotMatch(tsx, /from '\.\.\/\.\.\/v2\//);
  // 数字列（SPEC 数/问题阻塞/活跃运行）单元格水平居中（2026-11-06 用户指令）
  assert.equal((tsx.match(/align: 'center'/g) || []).length, 3);
});

test('global.less 必须保留台账表格磁贴规则（fixed 布局防撑坏 + 表头透明）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(less, /\.ov-bento \{/);
  assert.match(less, /\.ov-bento-table \.ant-table table \{\s*table-layout: fixed !important;/);
  assert.match(less, /\.ov-bento-table \.ant-table-thead > tr > th \{\s*background: transparent !important;/);
  // 过滤 Radio 激活态黑底白字覆写类在场（DESIGN.md 一般域条款，单源 .ov-radio-dark）
  assert.match(less, /\.ov-radio-dark \.ant-radio-button-wrapper-checked \{\s*background: #0f1115;/);
  assert.doesNotMatch(less, /\.ov-bento \.ant-radio-button-wrapper-checked/);
});

test('过滤 Radio 组消费 .ov-radio-dark 覆写类（overview 运行态 + projects 类型/归档两过滤组）', () => {
  const ov = readFileSync(
    join(STATIC_ROOT, 'src', 'pages', 'overview', 'components', 'ProjectTable.tsx'),
    'utf8',
  );
  assert.match(ov, /<Radio.Group\s+className="ov-radio-dark"/);
  const list = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'projects', 'list.tsx'), 'utf8');
  // 类型过滤 + 归档切换两组（2026-11-06 用户指令：参考 overview 样式处理）
  assert.equal((list.match(/className="ov-radio-dark"/g) || []).length, 2);
});

test('projects 桌面 SPEC 表格=Bento 台账磁贴（2026-11-06 用户指令对齐 v2；antd Table 功能保留）', () => {
  const tsx = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'projects', 'list.tsx'), 'utf8');
  // 磁贴包裹 + 台账表格内部样式挂点（边框对齐 v2，表格本体仍是 antd 控件）
  assert.match(tsx, /<div className="ov-bento">\s*<div className="ov-bento-table">/);
  // antd Table 功能不退役：固定布局/表头排序/分页换页大小/树形展开
  // （信息子行 add-spec-info-icon-tooltip 退役——信息收敛为状态旁图标 Popover）
  assert.match(tsx, /tableLayout="fixed"/);
  assert.match(tsx, /sorter: \(a: SpecSummary/);
  assert.match(tsx, /showSizeChanger: true/);
  assert.doesNotMatch(tsx, /expandedRowRender/);
  assert.doesNotMatch(tsx, /rowExpandable/);
  // 行内容 v2 形态挂点：状态/模式胶囊、名称 dense、验证 pill、进度阶段名行
  assert.match(tsx, /<Pill tone=\{m\.tone\}>\{m\.label\}<\/Pill>/);
  assert.match(tsx, /<SpecNameCell project=\{project\} record=\{record\} dense \/>/);
  assert.match(tsx, /<VerifyCell project=\{project\} record=\{record\} pill \/>/);
  assert.match(tsx, /data-testid="task-progress-cell"/);
  // 操作列=三点触发器 + 文档并入菜单首项（2026-11-06 用户指令，与 overview 台账同款）
  assert.match(tsx, /items: \[\{ key: 'doc', label: '文档' \}, \.\.\.\(menuItems\(record\) \|\| \[\]\)\]/);
  assert.match(tsx, /icon=\{<DotsIcon \/>\} aria-label="更多操作"/);
  // 状态/模式两列等宽收窄（2026-11-06 用户指令：width 同为 7%）
  assert.equal((tsx.match(/width: '7%'/g) || []).length, 2);
  // 镜像纪律：不得跨域 import v2 主题（例外域配色单源）
  assert.doesNotMatch(tsx, /from '@\/pages\/v2\//);
});

test('spec 详情顶栈卡片=Bento 皮肤 + 任务清单 v2 行渲染（2026-11-06 用户指令）', () => {
  const tsx = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'projects', 'detail.tsx'), 'utf8');
  // 五张顶栈卡片挂 .spec-bento-card（项目信息/任务清单/质量门禁/验证进度/验证结论）
  assert.equal((tsx.match(/className="[^"]*spec-bento-card/g) || []).length, 5);
  // 页签区卡不入 bento（2026-11-06 二次指令：tab 菜单避免卡套卡）
  assert.match(tsx, /<Card className="spec-detail-card">/);
  assert.doesNotMatch(tsx, /spec-detail-card spec-bento-card/);
  // 内容区顶呼吸带标记类在场（global.less :has() 规则的探测挂点）
  assert.match(tsx, /className="spec-detail-page"/);
  // 任务清单行渲染 = v2 形态（勾选块/空心圆 + mono 编号/描述 + 发丝线分隔）
  assert.match(tsx, /className="ov-task-check"/);
  assert.match(tsx, /className="ov-mono"/);
  // 未完成指示器=空心方框（2026-11-06 用户指令「未勾选保持方形」，任务+质量门禁
  // 两处消费；v2 TaskCard 原形为空心圆，本页偏离镜像源勿回填）
  assert.equal((tsx.match(/className="ov-task-empty"/g) || []).length, 2);
  const lessAll = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(lessAll, /\.ov-task-empty \{[\s\S]*?border-radius: 4px;/);
  // 质量门禁行渲染同款（2026-11-06 用户指令）：勾选块指示器 + 发丝线行分隔，
  // 状态语义（gateTextColor/后缀/detail）保留；antd Checkbox 已退役
  assert.match(tsx, /data-testid="quality-gate-item"\s*\n\s*style=\{\{ display: 'flex', gap: 10, padding: '7px 0', borderBottom: `1px solid \$\{OV_HAIRLINE\}` \}\}/);
  assert.doesNotMatch(tsx, /<Checkbox/);
  // 原内容契约钉子不丢：run 线索/空态 testid 与质量门禁卡
  assert.match(tsx, /data-testid="run-progress-hint"/);
  assert.match(tsx, /data-testid="run-progress-current"/);
  assert.match(tsx, /data-testid="run-activity-active"/);
  assert.match(tsx, /data-testid="tasks-note-warning"/);
  assert.match(tsx, /data-testid="quality-gates-card"/);
  // 镜像纪律：不得跨域 import v2 主题（例外域配色单源）
  assert.doesNotMatch(tsx, /from '@\/pages\/v2\//);
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(less, /#root \.spec-bento-card\.ant-card\.ant-card-bordered \{\s*border: 1px solid #eef2f7;\s*border-radius: 12px;/);
  assert.match(less, /\.ov-task-check \{[\s\S]*?border-radius: 4px;/);
  // 页签区包裹卡卡体归零（纯布局壳；否则 24px 使页签内容比上方 bento 卡多缩进一圈）
  assert.match(less, /#root \.spec-detail-card > \.ant-card-body \{\s*padding: 0;/);
  // 顶呼吸带三连（standalone 16px / embed 豁免归零 / 下游 24px）——数值单源
  // DESIGN.md 一般域「页面内容区间距」条款
  assert.match(less, /#root \.ant-layout-content:has\(\.spec-detail-page\) \{\s*padding-top: 16px;/);
  assert.match(less, /html\[data-embed-mode\] #root \.ant-layout-content:has\(\.spec-detail-page\) \{\s*padding-top: 0;/);
  assert.match(less, /html\[data-embed-mode\] #root \.spec-detail-page > \.ant-pro-page-container \{\s*padding-top: 24px;/);
});

test('时间轴节点=独立 Bento 磁贴（2026-11-06 用户指令；urgent 警示描边保留）', () => {
  const tsx = readFileSync(
    join(STATIC_ROOT, 'src', 'pages', 'projects', 'components', 'SpecTimeline.tsx'),
    'utf8',
  );
  assert.match(tsx, /borderRadius: 12/);
  assert.match(tsx, /1px solid \$\{OV_TILE_BORDER\}/);
  assert.match(tsx, /boxShadow: OV_TILE_SHADOW/);
  // 镜像纪律：不得跨域 import v2 主题（例外域配色单源）
  assert.doesNotMatch(tsx, /from '@\/pages\/v2\//);
});

test('配置页全量卡片=Bento 边框（2026-11-06 用户指令；直角化规则后置覆写、浅灰卡底保留）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  // 灰底准例（DESIGN.md 通用条款注记）：10px 圆角 + 加深边框 #d7d7d7——灰底上
  // #eef2f7 发丝线不可辨
  assert.match(less, /#root \.settings-page \.ant-card\.ant-card-bordered \{\s*border: 1px solid #d7d7d7;\s*border-radius: 10px;/);
  // 覆写顺序：Bento 规则必须在直角化规则（border-radius: 0）之后
  assert.ok(
    less.indexOf('#root .settings-page .ant-card.ant-card-bordered {\n  background-color: #f6f6f6;') <
    less.indexOf('#root .settings-page .ant-card.ant-card-bordered {\n  border: 1px solid #d7d7d7;'),
    '配置页 Bento 边框规则须后置于灰底直角化规则之后（同特异性靠后置生效）',
  );
  // 卡头随卡根圆角同形
  assert.match(less, /#root \.settings-page \.ant-card\.ant-card-bordered > \.ant-card-head \{\s*border-radius: 10px 10px 0 0;/);
});

test('Bento 磁贴圆角固定 12px（DESIGN.md 通用条款）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(less, /\.ov-bento \{[\s\S]*?border-radius: 12px;/);
  // 独立胶囊筛选形态不得回潮（2026-11-06 用户指令撤退）
  assert.doesNotMatch(less, /\.ov-chip/);
});

test('global.less 必须保留页头标题行避让规则（侧栏折叠钮悬浮于内容区左缘标题带内）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    text,
    /#root \.ant-pro-page-container > \.ant-page-header \{\s*padding-inline: 24px;\s*padding-block-end: 0;/,
  );
});

test('设置页隐形包裹卡 body 内边距全档归零（包裹卡纯布局壳；纵向节奏由卡内左菜单/右栏 padding 自承担）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  // 2026-11-05 用户指令：原 2026-11-04 版 padding: 24px 0（左右归零上下保留）
  // 升级为全档归零，卡内左菜单 paddingTop:16 与右栏 padding 上 8 下 24 分自承担
  assert.match(text, /#root \.settings-page > \.ant-card-body \{\s*padding: 0;/);
});

test('设置页面板卡头底线必须去除（body 顶缘唯一可见线源；灰底双档已承担分隔）', () => {
  const text = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    text,
    /#root \.settings-page \.ant-card\.ant-card-bordered > \.ant-card-head \{\s*border-bottom: 0;/,
  );
});

test('项目页包裹卡 body 内边距必须收紧到 8px（类名单源在 list.tsx 包裹卡上）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(less, /#root \.projects-page > \.ant-card-body \{\s*padding: 8px;/);
  const tsx = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'projects', 'list.tsx'), 'utf8');
  assert.match(tsx, /<Card variant="borderless" className="projects-page">/);
});

test('设置页文档级滚动形态必须保持：无定高常数、无卡体 flex 传导、右栏无内滚、菜单 sticky 钉住（2026-11-05）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  // 定高形态的两条 CSS 支撑（卡体 flex 传导高度链 + 负右外边距贴缘）不得回潮
  assert.doesNotMatch(
    less,
    /\.settings-page\s*>\s*\.ant-card-body \{\s*height: 100%;/,
  );
  assert.doesNotMatch(
    less,
    /\.settings-page \{\s*margin-right: -15px;/,
  );
  const tsx = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'settings', 'index.tsx'), 'utf8');
  // SETTINGS_FRAME_OFFSET 常数与 calc(100vh) 卡高已退役（帮助页同批，见
  // helpPageScroll.test.mjs）；旧双档 124/68（含页头）、56/48 与 60 档见 git
  // 历史。视口 calc 只允许出现在菜单 sticky 的 maxHeight（钉住预算），任何
  // height: calc(100vh) 高度链回潮即违规
  assert.doesNotMatch(tsx, /const SETTINGS_FRAME_OFFSET/);
  assert.doesNotMatch(tsx, /height: `calc\(100vh/);
  assert.match(tsx, /maxHeight: `calc\(100vh - \$\{SETTINGS_MENU_STICKY_TOP\}px - 16px\)`/);
  // 菜单本体 sticky 钉住（2026-11-05 用户指令「菜单/目录不能滚走」），
  // 钉住偏移双档实测值锁定：standalone 顶栏 56 / embed 行壳位 60
  assert.match(tsx, /position: 'sticky',\s*top: SETTINGS_MENU_STICKY_TOP,/);
  assert.match(tsx, /const SETTINGS_MENU_STICKY_TOP = isEmbedMode\(\) \? 60 : 56;/);
  // 右栏不得自带纵向滚动条：页面纵向滚动统一落在文档上（菜单 sticky 本体的
  // overflowY auto 是长菜单钉位自滚兜底，豁免）
  assert.doesNotMatch(tsx, /flex: 1,\s*minWidth: 0,\s*padding: '8px 16px 24px 24px',[^}]*overflowY/);
});

test('页面内容区卡片阴影必须移除（antd v6 卡默认 0.05 微阴影=白底上的隐形边）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    less,
    /#root \.ant-pro-page-container \.ant-card \{\s*box-shadow: none;/,
  );
});

test('设置页面板 body 内边距禁止归零（padding 0 曾使表单网格/计费子行贴死面板四缘，2026-11-04 实证布局散架已回退）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.doesNotMatch(
    less,
    /#root \.settings-page \.ant-card\.ant-card-bordered > \.ant-card-body \{\s*padding: 0;/,
  );
});

test('设置页卡体归零 + 右栏右呼吸 16px 单源（贴缘负右外边距已随内滚退役，防回潮见「文档级滚动形态」测试）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    less,
    // 卡体块尾归零由基础规则 padding:0 承担（2026-11-05 全档归零后 flex 规则的
    // padding-block-end:0 长写补丁已回收，global.less 注释有交代）
    /#root \.settings-page > \.ant-card-body \{\s*padding: 0;/,
  );
  // 右呼吸 16px 已从 `.ant-form`（只覆盖 Form 面板，提示词/项目/Hook 漏）单源
  // 上收到右栏本体（2026-11-05 用户指令「各页签右间距统一」）：新源在 index.tsx
  // 右栏内联 padding，旧规则防回潮（回潮即 Form 面板右 32 双源）
  assert.doesNotMatch(less, /#root \.settings-page \.ant-form \{[^}]*padding-right/);
  const tsx = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'settings', 'index.tsx'), 'utf8');
  assert.match(tsx, /padding: '8px 16px 24px 24px'/);
});

test('设置页面板直角化：卡根与卡头 border-radius 0（圆角灰底剪影即「圆角边框」来源）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    less,
    /#root \.settings-page \.ant-card\.ant-card-bordered \{\s*background-color: #f6f6f6;[^}]*border-radius: 0;/,
  );
  assert.match(
    less,
    /#root \.settings-page \.ant-card\.ant-card-bordered > \.ant-card-head \{\s*background-color: #efefef;\s*border-radius: 0;/,
  );
});

test('设置页页头 heading 12px 块尾补偿必须保持退役（PageContainer 页头已摘除，补偿对象不复存在）', () => {
  // unified-page-title-bar 2.2：页头消失后 12px padding-block-end 补偿随页头
  // 一起退役（global.less 保留退役说明注释）；规则回潮会在无页头的现实下
  // 悬空空转，且 :has 选择器依赖 .ant-page-header-heading 元素不再渲染
  assert.doesNotMatch(
    readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8'),
    /\.ant-page-header-heading \{\s*padding-block-end: 12px;/,
  );
});

test('菜单选中底统一=黑 4% alpha（与 ProLayout 侧栏看齐；冷灰 10% 在内层菜单显著偏深）', () => {
  const theme = readFileSync(join(STATIC_ROOT, 'src', 'theme.ts'), 'utf8');
  assert.match(theme, /export const DSH_MENU_SELECTED_BG = 'rgba\(0, 0, 0, 0\.04\)';/);
  assert.match(theme, /itemSelectedBg: DSH_MENU_SELECTED_BG,/);
  assert.match(theme, /itemActiveBg: 'rgba\(0, 0, 0, 0\.06\)'/);
  const help = readFileSync(join(STATIC_ROOT, 'src', 'pages', 'help', 'index.tsx'), 'utf8');
  assert.match(help, /background: DSH_MENU_SELECTED_BG/);
  assert.doesNotMatch(help, /DSH_INTERACTIVE_ACTIVE/);
});

test('侧栏「项目」二级菜单限高滚动（2026-11-06 用户指令：对齐 dsh web 工作区——固定显示 5 个项目，超出滚动条）', () => {
  const less = readFileSync(join(STATIC_ROOT, 'src', 'global.less'), 'utf8');
  assert.match(
    less,
    /li\.ant-menu-submenu > ul\.ant-menu-sub\.ant-menu-inline \{\s*max-height: 200px;\s*overflow-y: auto;\s*scrollbar-gutter: stable;\s*\}/,
  );
  // 滚动条同款 dsh web（2026-11-06 用户指令：6px 滑块/无上下箭头/轨道透明；
  // 中性灰 alpha 滑块亮暗主题通用）。同一选择器作用域，页面其他滚动条零波及。
  assert.match(
    less,
    /li\.ant-menu-submenu > ul\.ant-menu-sub\.ant-menu-inline::-webkit-scrollbar \{\s*width: 6px;\s*\}/,
  );
  assert.match(
    less,
    /::-webkit-scrollbar-thumb \{\s*border-radius: 3px;\s*background-color: rgba\(127, 127, 127, 0\.5\);\s*\}/,
  );
  assert.match(
    less,
    /::-webkit-scrollbar-track \{\s*background-color: transparent;\s*\}/,
  );
  assert.match(
    less,
    /::-webkit-scrollbar-button \{\s*display: none;\s*\}/,
  );
});
