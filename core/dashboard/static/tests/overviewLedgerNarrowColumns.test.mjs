// overview 台账窄视口列宽双档守卫（2026-11-16 用户指令两连：小宽度下避免横向
// 滚动条；页面缩小时大部分空间从项目列出、其余各列适当贡献一点）。
//
// 机制：viewport <1200（antd xl 断点，umi screen-md/sm/xs/lg）时其余五列从
// 96/220/108/108/72（合计 604）收到可读下限 80/190/92/92/56（合计 510，
// 其余列让位 94px），项目列无宽度吃剩余；scroll.x 同步 890→700（=510+项目
// 列最小 190），无横向滚动条的容器下限从 890 扩到 700（覆盖 994px 视口
// sider 展开态容器 706）。宽档数值不动 = PC（≥1200）零影响。
//
// 零依赖 node:test 源码扫描（同 pageChrome.test.mjs 习语）；视觉行为由
// `npm run build` 与浏览器冒烟覆盖，本文件锁定双档数值与断点接线。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const STATIC_ROOT = join(import.meta.dirname, '..');
const readTsx = () =>
  readFileSync(
    join(STATIC_ROOT, 'src', 'pages', 'overview', 'components', 'ProjectTable.tsx'),
    'utf8',
  );

test('台账列宽双档数值在场（宽档原值 / 窄档可读下限）', () => {
  const tsx = readTsx();
  assert.match(
    tsx,
    /wide: \{ spec: 96, progress: 220, problems: 108, activeRuns: 108, actions: 72 \}/,
    '宽档列宽必须维持原值（PC ≥1200 零影响），勿顺手调整',
  );
  assert.match(
    tsx,
    /narrow: \{ spec: 80, progress: 190, problems: 92, activeRuns: 92, actions: 56 \}/,
    '窄档下限数值（合计 510，其余列让位 94px）勿回退为单档',
  );
});

test('列宽消费 ledgerWidths 双档对象（勿回退单档字面量）', () => {
  const tsx = readTsx();
  for (const key of ['spec', 'progress', 'problems', 'activeRuns', 'actions']) {
    assert.match(
      tsx,
      new RegExp(`width: ledgerWidths\\.${key}\\b`),
      `「${key}」列宽必须走 ledgerWidths 双档`,
    );
  }
  assert.doesNotMatch(tsx, /width: (?:96|220|108|72)\b/);
});

test('scroll.x 双档接线 + 窄档断点挂 <1200（useMediaQuery）', () => {
  const tsx = readTsx();
  assert.match(tsx, /scroll=\{\{ x: narrowLedger \? 700 : 890 \}\}/);
  assert.match(tsx, /const narrowLedger = useMediaQuery\(NARROW_LEDGER_QUERY\)/);
  assert.match(tsx, /NARROW_LEDGER_QUERY = '\(max-width: 1199\.98px\)'/);
  // 钩子实现：首帧同步取值（无闪动）+ 卸载清理
  const hook = readFileSync(join(STATIC_ROOT, 'src', 'hooks', 'useMediaQuery.ts'), 'utf8');
  assert.match(hook, /matchMedia\(query\)\.matches : false/);
  assert.match(hook, /removeEventListener\('change', onChange\)/);
});
