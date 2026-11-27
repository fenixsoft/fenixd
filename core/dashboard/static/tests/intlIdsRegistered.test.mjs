// intl id 登记全仓守卫（i18n 修复轮：指挥中心/质量分面裸键名事故防再犯）。
//
// 事故形态（2026-11-27 用户报告）：QualityTab STATUS_FILTER_OPTIONS 把状态下拉
// 选项 label 映射到 'projects.quality.status.*' 键，渲染时
// intl.formatMessage({ id: o.label })——但 7 个键均未在 zh-CN.ts / en-US.ts
// 登记，umi 缺失 id 回退返回键名本身，下拉渲染裸键名。activities 页同型事故
// 已有页级守卫（activitiesOpsIntlIds.test.mjs），本守卫升级为全仓静态扫描：
//
//   ① formatMessage({ id: 'x.y.z' }) 字面量 id；
//   ② intlText('x.y.z') 字面量 id（非组件 shim）；
//   ③ label: 'x.y.z' 形态的「键形字面量」（选项词典经 formatMessage({id})
//      间接渲染——本次事故的逃逸通道）；
//   ④ 动态拼键（`prefix.${v}`）不可静态解析，降级断言目录存在该前缀族。
//
// 全部要求键已在 zh 目录登记（zh 目录是唯一回退底座；en 覆盖由 en-US.ts
// enOverrides 承载，其 ⊆ zh 键集已由 localePreference.test.mjs 断言）。
//
// 零依赖 node:test 源码扫描（同 activitiesOpsIntlIds.test.mjs 习语）。
// 运行：cd core/dashboard/static && node --test tests/intlIdsRegistered.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import zhCN from '../src/locales/zh-CN.ts';

const SRC_ROOT = fileURLToPath(new URL('../src', import.meta.url));
const sep = process.platform === 'win32' ? '\\' : '/';

// 键形字面量白名单：形似目录键但实为业务值（文件名/枚举原样展示）。
// 登记新键形字面量撞名时在此豁免并注明用途。
const ALLOWLIST = new Set([
  'scheduler.py', // projectHomeShared.ts：调度器脚本文件名字面量
]);

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (/\.(ts|tsx)$/.test(name) && !p.includes(`${sep}locales${sep}`)) yield p;
  }
}

const files = [...walk(SRC_ROOT)];
assert.ok(files.length > 50, '源码扫描应覆盖全仓（扫描器失配即守卫失效）');

test('全仓 formatMessage/intlText 字面量 id 与 label 键形字面量均已在 zh 目录登记', () => {
  const missing = new Map(); // id -> [file]
  const dynamicPrefixes = new Set(); // `prefix.${v}` 动态拼键前缀族
  const literalRe =
    /formatMessage\(\{\s*id:\s*'([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+)'/g;
  const intlTextRe = /\bintlText\(\s*'([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+)'/g;
  // label: 'x.y.z' —— 选项词典把目录键当 label 存、渲染期 formatMessage 展开
  const labelRe =
    /\blabel:\s*'([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+){1,4})'/g;
  // 动态拼键：formatMessage({ id: `prefix.${...}` })
  const dynamicRe = /formatMessage\(\{\s*id:\s*`([a-z][A-Za-z0-9.]*)\.\$\{/g;

  for (const file of files) {
    const text = readFileSync(file, 'utf8');
    for (const re of [literalRe, intlTextRe, labelRe]) {
      for (const m of text.matchAll(re)) {
        const id = m[1];
        if (ALLOWLIST.has(id) || id in zhCN) continue;
        if (!missing.has(id)) missing.set(id, []);
        missing.get(id).push(file.slice(SRC_ROOT.length + 1));
      }
    }
    for (const m of text.matchAll(dynamicRe)) dynamicPrefixes.add(m[1]);
  }

  assert.deepEqual(
    [...missing.entries()].map(([id, fs]) => `${id} => ${fs.join(', ')}`),
    [],
    '源码引用了 zh 目录未登记的 intl id（渲染将裸露键名，umi formatMessage 缺 id 回退键名本身）',
  );

  // 动态族至少存在一个同前缀目录键（防整族漏登记）
  for (const prefix of dynamicPrefixes) {
    assert.ok(
      Object.keys(zhCN).some((k) => k.startsWith(`${prefix}.`)),
      `动态拼键前缀族「${prefix}.*」在 zh 目录无任何登记键`,
    );
  }
});
