// resolveHealthCheckParams 单元测试（零依赖，node 原生 type-stripping 加载 .ts）。
// 运行：cd core/dashboard/static && node --test tests/llmHealth.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveHealthCheckParams } from '../src/utils/llmHealth.ts';

const FORM = [{ name: ' p-a ', baseurl: 'https://a.example.com', apikey: 'sk-a', model: 'a-default' }];
const SAVED = [{ name: 'p-saved', baseurl: 'https://s.example.com/', apikey: 'sk-s', model: 's-default' }];

test('行内模型已填：优先用行内值（角色级/Provider 默认在场也不覆盖）', () => {
  const r = resolveHealthCheckParams({
    formProviders: FORM,
    savedProviders: [],
    providerName: 'p-a',
    rowModel: ' mdl-x ',
    roleModel: 'role-m',
  });
  assert.deepEqual(r, { baseurl: 'https://a.example.com', apikey: 'sk-a', model: 'mdl-x' });
});

test('行内留空走角色级缺省', () => {
  const r = resolveHealthCheckParams({
    formProviders: FORM,
    providerName: 'p-a',
    rowModel: '',
    roleModel: 'role-default',
  });
  assert.equal('error' in r, false);
  assert.equal(r.model, 'role-default');
});

test('角色级也空走 Provider 默认模型', () => {
  const r = resolveHealthCheckParams({
    formProviders: FORM,
    providerName: 'p-a',
    rowModel: '',
    roleModel: '',
  });
  assert.equal('error' in r, false);
  assert.equal(r.model, 'a-default');
});

test('Provider 仅在已保存配置中（表单回退命中）', () => {
  const r = resolveHealthCheckParams({
    formProviders: [],
    savedProviders: SAVED,
    providerName: 'p-saved',
    rowModel: '',
    roleModel: '',
  });
  assert.equal('error' in r, false);
  assert.equal(r.baseurl, 'https://s.example.com/');
  assert.equal(r.apikey, 'sk-s');
  assert.equal(r.model, 's-default');
});

test('表单值优先于已保存配置（未保存修改即测语义）', () => {
  const edited = [{ name: 'p-a', baseurl: 'https://edited.example.com', apikey: 'sk-edited', model: '' }];
  const r = resolveHealthCheckParams({
    formProviders: edited,
    savedProviders: FORM,
    providerName: 'p-a',
    rowModel: 'm1',
  });
  assert.equal(r.baseurl, 'https://edited.example.com');
  assert.equal(r.apikey, 'sk-edited');
});

test('两处都无：返回 error 并指明 Provider 名', () => {
  const r = resolveHealthCheckParams({
    formProviders: FORM,
    savedProviders: SAVED,
    providerName: 'p-ghost',
    rowModel: '',
  });
  assert.equal('error' in r, true);
  assert.match(r.error, /p-ghost/);
});

test('模型链全空（行内/角色级/Provider 默认均无）：返回 error', () => {
  const noDefault = [{ name: 'p-a', baseurl: 'https://a.example.com', apikey: 'sk-a' }];
  const r = resolveHealthCheckParams({
    formProviders: noDefault,
    providerName: 'p-a',
    rowModel: '',
    roleModel: '',
  });
  assert.equal('error' in r, true);
  assert.match(r.error, /模型/);
});

test('Provider 缺 baseurl：返回 error（前置拦截不发请求）', () => {
  const noUrl = [{ name: 'p-a', apikey: 'sk-a', model: 'm' }];
  const r = resolveHealthCheckParams({ formProviders: noUrl, providerName: 'p-a' });
  assert.equal('error' in r, true);
  assert.match(r.error, /Base URL/);
});

test('Provider 名为空：返回 error', () => {
  const r = resolveHealthCheckParams({ formProviders: FORM, providerName: '  ' });
  assert.equal('error' in r, true);
  assert.match(r.error, /Provider/);
});
