// llmHealth.ts — LLM Provider 健康检测的检测目标解析（add-provider-health-check 3.2）。
// 纯函数零 React 依赖（范式同 agentModels.ts），供「模型分配」页签行内健康检测
// 按钮使用：按运行期同款链解析实际检测目标（design D6）。
// 文案经 useIntl/getIntl（i18n 修复轮 batch-A：本文件静态中文文案迁 i18n 目录）
// ——前置校验/结果短语经 utils/intlText.ts 渲染期取值（raw node 测试链回落 zh 目录）。
import type { LlmHealthCheckResult, LlmProvider } from '@/services/dashboard';
import { intlText } from './intlText.ts';

export interface HealthCheckParams {
  baseurl: string;
  apikey: string;
  model: string;
}

/** 解析结果：成功返回三字段检测参数，失败返回 { error: <原因> }（调用方
    直接提示、不发请求）。用 'error' in r 判别分支（in 收窄对两分支成员可靠）。 */
export type HealthCheckResolution = HealthCheckParams | { error: string };

export interface ResolveHealthCheckOptions {
  /** 表单正在编辑的 Provider 列表（表单当前值语义：未保存修改即测） */
  formProviders?: Array<Partial<LlmProvider>>;
  /** 已保存配置（当前作用域 config）的 Provider 列表（回退源） */
  savedProviders?: Array<Partial<LlmProvider>>;
  /** 行内所选 Provider 名 */
  providerName?: string;
  /** 行内模型输入 */
  rowModel?: string;
  /** 所在角色卡片的「角色级默认模型」 */
  roleModel?: string;
}

function byName(
  list: Array<Partial<LlmProvider>> | undefined,
  name: string,
): Partial<LlmProvider> | undefined {
  return (list || []).find((p) => ((p?.name as string) || '').trim() === name);
}

export function resolveHealthCheckParams(opts: ResolveHealthCheckOptions): HealthCheckResolution {
  const providerName = (opts.providerName || '').trim();
  if (!providerName) {
    return { error: intlText('utils.llmHealth.noProvider') };
  }
  // baseurl/apikey 先按名查表单当前值，查不到回退已保存配置（spec：
  // 引用仅存在于已保存配置的 Provider 时从已保存配置解析）
  const provider = byName(opts.formProviders, providerName) ?? byName(opts.savedProviders, providerName);
  if (!provider) {
    return { error: intlText('utils.llmHealth.providerMissing', { name: providerName }) };
  }
  const baseurl = ((provider.baseurl as string) || '').trim();
  if (!baseurl) {
    return { error: intlText('utils.llmHealth.missingBaseUrl', { name: providerName }) };
  }
  const apikey = ((provider.apikey as string) || '').trim();
  if (!apikey) {
    return { error: intlText('utils.llmHealth.missingApiKey', { name: providerName }) };
  }
  // 模型链（design D6）：行内模型 → 角色级默认模型 → Provider 默认模型
  const model =
    (opts.rowModel || '').trim() ||
    (opts.roleModel || '').trim() ||
    ((provider.model as string) || '').trim();
  if (!model) {
    return {
      error: intlText('utils.llmHealth.modelEmpty', { name: providerName }),
    };
  }
  return { baseurl, apikey, model };
}

/** 健康检测结果的内联展示形态：成功绿色「正常 · X.Xs」、失败红色
    「失败 · <error_kind>」+ tooltip 完整错误（两处面板共用口径，spec 4.1/4.2）。 */
export interface HealthCheckDisplay {
  kind: 'ok' | 'fail';
  short: string;
  tooltip: string;
}

/** 后端检测结果 → 标题栏/行内展示形态（耗时秒一位小数）。 */
export function toHealthDisplay(r: LlmHealthCheckResult): HealthCheckDisplay {
  // 非有限值（NaN/±Infinity）防御（code-review item cb2dde8cbbcc）：latency_ms
  // 缺失/非数值时耗时段回退「—」，不向展示层透传「正常 · NaNs」（对齐
  // @/utils/duration、@/utils/percent 的既有防御口径）。
  const ms = Number.isFinite(r.latency_ms) ? r.latency_ms : null;
  const seconds = ms === null ? '—' : `${(ms / 1000).toFixed(1)}s`;
  if (r.ok) {
    return {
      kind: 'ok',
      short: intlText('utils.llmHealth.okShort', { seconds }),
      tooltip: intlText('utils.llmHealth.okTooltip', { model: r.model || '', seconds }),
    };
  }
  const kind = r.error_kind || intlText('utils.llmHealth.unknownKind');
  return {
    kind: 'fail',
    short: intlText('utils.llmHealth.failShort', { kind }),
    tooltip: r.error ? intlText('utils.llmHealth.failTooltip', { kind, error: r.error }) : kind,
  };
}
