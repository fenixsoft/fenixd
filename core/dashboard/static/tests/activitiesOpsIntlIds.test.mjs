// 运维页 activities intl id 登记守卫（code-review item 5f09c72b9cba 防再犯）。
//
// 事故形态：RESULT_META 把 7 种处置结果映射到 'ops.result.*' 键，但 zh-CN.ts /
// en-US.ts 目录均未登记——react-intl 缺失 id 回退返回键名本身，页面渲染裸键名
// （ops.result.resolved）并伴控制台报错。本守卫锁死「源码引用 id ∈ zh 目录键集」：
// activities 页源码中出现的全部 ops.* 文案 id，必须先在 zh 目录登记（en 覆盖
// 由 en-US.ts enOverrides 承载，其 ⊆ zh 键集已由 localePreference.test.mjs 断言）。
//
// 零依赖 node:test 源码扫描（同 knowledgeSettings.test.mjs 直载目录习语）。
// 运行：cd core/dashboard/static && node --test tests/activitiesOpsIntlIds.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import zhCN from '../src/locales/zh-CN.ts';

const SRC = readFileSync(
  new URL('../src/pages/activities/index.tsx', import.meta.url),
  'utf8',
);

test('activities 源码引用的 ops.* intl id 全部已在 zh 目录登记（缺键即裸键名回退）', () => {
  const catalog = zhCN;
  // 命中形态：源码里以字符串字面量出现的 ops.* id（formatMessage id: 与
  // RESULT_META labelId: 同型）。目录键集含 common.* 等非 ops 域，放行无碍。
  const refs = [...SRC.matchAll(/['"](ops\.[A-Za-z0-9.]+)['"]/g)].map((m) => m[1]);
  assert.ok(refs.length > 0, '扫描应命中至少一条 ops.* 引用（正则失配即守卫失效）');
  const missing = [...new Set(refs)].filter((id) => !(id in catalog));
  assert.deepEqual(
    missing,
    [],
    `activities 源码引用了 zh 目录未登记的 intl id（渲染将裸露键名）: ${missing.join(', ')}`,
  );
});
