// 暗种子 *Bg 派生 token 守卫（宿主对齐改造 2026-11-03 回归守卫）。
//
// theme.ts 把 colorPrimary 从蓝 #1677ff 改为 dsh 近黑 #0f1115 后，antd 以主色
// 为种子派生的 `--ant-color-primary-bg` 族（palette[1..3]）对暗种子生成**暗色**
// ramp（实测 #4f5254 起，node @ant-design/colors generate('#0f1115')）——任何
// 「选中底色」引用该族都会变成黑底黑字/深底深字，不可读。蓝种子时代该族是
// 浅蓝 #e6f4ff，两代行为相反，属设计内陷阱而非笔误，必须源码级禁用：
//
// - 选中/高亮底色一律取 theme.ts 单源常量（DSH_INTERACTIVE_ACTIVE，dsh 侧栏
//   选中行冷灰）或中性 fill 族（--ant-color-fill*，黑 alpha 与种子无关）；
//   对照先例：projects/list.tsx 行选中底、help 页目录 active 底（曾踩坑已修）。
//
// 零依赖 node:test 源码扫描（同 harnessBrand.test.mjs 习语）；React/样式装配
// 层的视觉行为由 `npm run build` 与浏览器冒烟覆盖，本文件锁定 token 引用面。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const SRC_ROOT = join(import.meta.dirname, '..', 'src');

// 递归收集源码文件（tsx/ts/css/less；排除 .umi 产物目录）
function collectSources(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    if (name === '.umi' || name === '.umi-production') continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...collectSources(p));
    else if (/\.(tsx?|css|less)$/.test(name)) out.push(p);
  }
  return out;
}

test('src 内禁止引用种子派生 --ant-color-primary-bg 族（暗主色下为暗色 ramp，黑底黑字陷阱）', () => {
  const offenders = [];
  for (const file of collectSources(SRC_ROOT)) {
    const text = readFileSync(file, 'utf8');
    // 命中形态：var(--ant-color-primary-bg) 及 -hover/-active 变体。theme.ts
    // 注释里的 camelCase（colorPrimaryBg）与「Bg 派生」叙述不匹配本形态，不误伤
    if (/var\(--ant-color-primary-bg[a-z-]*\)/.test(text)) offenders.push(file);
  }
  assert.deepEqual(
    offenders.map((p) => p.replace(SRC_ROOT + '/', '')),
    [],
    '以下文件引用了种子派生 --ant-color-primary-bg 族（暗主色下不可读），改用 theme.ts 单源选中底或中性 fill 族',
  );
});

test('Select 选项 hover/选中底必须显式压浅（暗主色种子下 controlItemBgHover/primaryBg 派生深色阶，黑字黑底陷阱——2026-11-04 指挥中心筛选下拉实测）', () => {
  // 与 Menu itemActiveBg 同款处方：凡 antd 缺省消费主色 Bg 派生族做「浅底」
  // 语义的组件键，theme.ts 必须显式给中性浅值，不得依赖种子派生。
  const text = readFileSync(join(SRC_ROOT, 'theme.ts'), 'utf8');
  const selectBlock = text.slice(text.indexOf('Select: {'), text.indexOf('Button: {'));
  assert.match(selectBlock, /optionActiveBg:\s*DSH_BG_MODULE/);
  assert.match(selectBlock, /optionSelectedBg:\s*DSH_BG_MODULE/);
  // 选中+hover 叠加态走全局别名（组件级键覆盖不到）——controlItemBgActive
  // 缺省=colorPrimaryBg（实测 #4f5254）/ActiveHover 缺省=派生 #434547
  assert.match(text, /controlItemBgActive:\s*DSH_BG_MODULE/);
  assert.match(text, /controlItemBgActiveHover:\s*DSH_BG_MODULE/);
});
