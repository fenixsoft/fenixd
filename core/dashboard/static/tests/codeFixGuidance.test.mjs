// codeFixGuidance 接线测试（i18n 修复轮 batch-P 改造：钉 intl id 接线而非中文串）。
// 原直载单测因模块改经 getIntl()（'@umijs/max' 运行时依赖）渲染期取文案而退役
// 直载，改用仓库习语另一支柱：源码扫描钉接线 + locale 目录交叉钉文案落点
// （模式同 specRowClick.test.mjs 头注释：零渲染纯逻辑直测 + 源码扫描）。
// 运行：cd core/dashboard/static && node --test tests/codeFixGuidance.test.mjs
//
// 覆盖（2026-09-25 用户要求「blocked 不能仅提示阻塞，须明确如何处理」）：
//  - 后端 code_fix.py 全部 blocked 写入点的 reason 键 → projects.codeFixBlocked.*
//    label/guidance intl 键映射（键漂移盘点）
//  - 全部 intl 键在 zh-CN.ts / en-US.ts 目录已登记（zh 为回退源，en 缺键会裸中文）
//  - 关键语义在 zh 文案中落点：wip_overlap 必须点名「提交或 stash」用户动作、
//    selfheal 类为「无需处理」语义、disabled 指向开关、契约类指向 verify.yaml
//  - 宁严勿松回退：未知 reason 原码透传 + unknownLabel/unknownGuidance 键登记
//  - selfheal 集合 / 已知性判定 / 原码括注组合仍在源码同点维护
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
  join(here, '../src/pages/projects/components/codeFixGuidance.ts'),
  'utf8',
);
const zh = readFileSync(join(here, '../src/locales/zh-CN.ts'), 'utf8');
const en = readFileSync(join(here, '../src/locales/en-US.ts'), 'utf8');

// 与 core/code_fix.py 2026-09-25 盘点的全部 blocked reason 同源；后端新增
// reason 时 blockedReasonInfo 回退仍可用，但应补映射（键漂移盘点口径不变）。
const BACKEND_REASONS = [
  'disabled',
  'failed_batch_retained',
  'failed_batch_maxed',
  'wip_gate_blocked',
  'wip_overlap_at_select',
  'regression_contract_missing',
  'regression_section_missing',
  'zero_progress_paused',
];

const camel = (r) => r.replace(/_([a-z])/g, (_, c) => c.toUpperCase());

// 从 locale 目录源码提取单键值（目录条目形态 `'key': 'value',`）
const localeVal = (catalog, key) => {
  const m = catalog.match(new RegExp(`'${key.replace(/\./g, '\\.')}':\\s*'((?:[^'\\\\]|\\\\.)*)'`));
  return m ? m[1] : null;
};

test('后端 blocked reason 全集 → projects.codeFixBlocked.* 键映射（键漂移盘点）', () => {
  for (const r of BACKEND_REASONS) {
    for (const suffix of ['label', 'guidance']) {
      const key = `projects.codeFixBlocked.${camel(r)}.${suffix}`;
      assert.ok(src.includes(`'${key}'`), `${r} 应映射到 intl 键 ${key}`);
    }
  }
});

test('全部 projects.codeFixBlocked.* 键在 zh-CN.ts 与 en-US.ts 已登记', () => {
  const keys = [];
  for (const r of BACKEND_REASONS) {
    keys.push(`projects.codeFixBlocked.${camel(r)}.label`);
    keys.push(`projects.codeFixBlocked.${camel(r)}.guidance`);
  }
  keys.push('projects.codeFixBlocked.unknownLabel');
  keys.push('projects.codeFixBlocked.unknownGuidance');
  for (const key of keys) {
    assert.ok(localeVal(zh, key) !== null, `${key} 缺 zh 登记（zh 为回退源）`);
    assert.ok(localeVal(en, key) !== null, `${key} 缺 en 覆盖`);
    assert.ok(!localeVal(zh, key).includes('\\u'), `${key} zh 值应为真实中文而非转义`);
  }
});

test('wip_overlap_at_select 文案点名「提交或 stash」用户动作与自动恢复', () => {
  const g = localeVal(zh, 'projects.codeFixBlocked.wipOverlapAtSelect.guidance');
  assert.match(g, /提交或 stash/);
  assert.match(g, /自动恢复/);
  const l = localeVal(zh, 'projects.codeFixBlocked.wipOverlapAtSelect.label');
  assert.match(l, /未提交改动/);
});

test('selfheal 等待类 reason 指引为「无需处理」语义', () => {
  for (const r of ['failed_batch_retained', 'wip_gate_blocked']) {
    const g = localeVal(zh, `projects.codeFixBlocked.${camel(r)}.guidance`);
    assert.match(g, /无需处理/, `${r} 应标明无需人工介入`);
  }
  // 集合与指引文案同在本文件同点维护（code-review item 5400cd0de2c3）
  assert.ok(src.includes("'wip_gate_blocked'") && src.includes("'failed_batch_retained'"));
  assert.match(src, /SELFHEAL_WAIT_REASONS/);
  assert.match(src, /export function isSelfhealWait/);
});

test('disabled 指引指向重新打开开关', () => {
  const g = localeVal(zh, 'projects.codeFixBlocked.disabled.guidance');
  assert.match(g, /开关/);
});

test('契约缺失类 reason 指引指向 verify.yaml', () => {
  for (const r of ['regression_contract_missing', 'regression_section_missing']) {
    const g = localeVal(zh, `projects.codeFixBlocked.${camel(r)}.guidance`);
    assert.match(g, /verify\.yaml/, `${r} 应指向 verify.yaml`);
  }
});

test('宁严勿松回退接线：unknownLabel/unknownGuidance 键登记且 zh 语义钉住', () => {
  assert.equal(localeVal(zh, 'projects.codeFixBlocked.unknownLabel'), '未知原因');
  assert.equal(localeVal(zh, 'projects.codeFixBlocked.unknownGuidance'), '需人工排查');
  assert.ok(
    src.includes("t('projects.codeFixBlocked.unknownLabel')") &&
      src.includes("t('projects.codeFixBlocked.unknownGuidance')"),
    '未知 reason 回退应走 unknownLabel/unknownGuidance 键',
  );
  assert.match(src, /label: reason \|\| t\('projects\.codeFixBlocked\.unknownLabel'\)/);
});

test('blockedReasonDisplay：已知 reason 原码括注、未知原样回显（组合仍在源码）', () => {
  // 括注改半角 ASCII 括号（code-review item e8d62418e0c6：标点不随 locale 残留全角）
  assert.match(src, /`\$\{t\(BLOCKED_REASONS\[reason\]\.labelId\)\} \(\$\{reason\}\)`/);
  assert.match(src, /: reason;/);
  assert.match(src, /export function blockedReasonDisplay/);
});

test('getIntl 渲染期求值接线（batch-P 规则 3：禁止模块顶层求值译文）', () => {
  assert.match(src, /import \{ getIntl \} from '@umijs\/max';/);
  assert.match(src, /try \{\s*\n\s*return getIntl\(\)\.formatMessage\(/);
  // 极端早调用回退 zh 目录查表（utils/format.ts 不抛错先例口径）
  assert.match(src, /zhCN as Record<string, string>/);
});
