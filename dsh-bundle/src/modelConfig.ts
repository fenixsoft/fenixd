/**
 * modelConfig.ts — 模型显式配置契约（OpenAI 兼容端点三要素）。
 *
 * 设计决策 4：模型配置采用「配置文件渲染」而非 env 传递——SPEC-3 的 dsh_adapter
 * 把 fenixd provider 链（name/baseurl/apikey/model）渲染为本插件 config 的 model
 * 段；本插件启动时校验 model 显式存在，缺失即抛「模型未显式配置」fail-fast
 * （铁律：绝不依赖 dsh 默认档，承袭 narrative 网关别名事故）。
 *
 * 渲染产物：
 * - providers —— 挂到 dsh-base 的 llm-pi-ai 条目 config.providers
 *   （OpenAI 兼容端点：api=openai-completions + baseURL + apiKeyEnv + models 目录）；
 * - provider / model —— 挂到 agent-default-model 条目，指定默认路由与模型。
 *
 * fail-fast 通道：校验失败在本插件 apply 内抛错 → fenixModelConfig 服务缺失 →
 * 依赖它的 llm-pi-ai / agent-default-model / headless-runner（dsh required 启动
 * 条目，cordis.patch.yml 已追加注入）一起失败 → StartupError exit 1。
 *
 * 纯逻辑（校验与渲染段构造）与 dsh 装配分离：单测零 dsh 依赖。
 */

import { assertDshPinned } from "./version.ts";

// ── 纯逻辑：三要素校验与渲染 ───────────────────────────────────────────────

/** SPEC-3 渲染的模型配置段（fenixd provider 链的 dsh 投影）。 */
export interface FenixModelSegment {
  /** provider 路由名（fenixd provider 链 name）。 */
  provider: string;
  /** OpenAI 兼容端点根（如 http://127.0.0.1:18787/v1）。 */
  baseURL: string;
  /** 携带 API key 的环境变量名（dsh credentials 服务按名解析；不传值本身）。 */
  apiKeyEnv: string;
  /** 模型 id——MUST 显式存在，缺失/为空即 fail-fast。 */
  model: string;
  /** 线协议；缺省 openai-completions。 */
  api?: string;
  /** 模型目录元数据（可选项，缺省注入 DEFAULT_MODEL_CONTEXT_WINDOW=262144，不省略字段）。 */
  contextWindow?: number;
  maxTokens?: number;
  /** 附加请求头（可选）。 */
  headers?: Record<string, string>;
}

export const DEFAULT_MODEL_CONTEXT_WINDOW = 262144;
export const DEFAULT_MODEL_MAX_TOKENS = 32768;

/** 校验 model 段显式存在且三要素齐备；不满足抛「模型未显式配置」。 */
export function assertModelExplicit(segment: unknown): FenixModelSegment {
  if (typeof segment !== "object" || segment === null || Array.isArray(segment)) {
    throw new Error(
      "模型未显式配置：fenix-dsh-bundle 要求 config.model 显式给出 provider/baseURL/apiKeyEnv/model 三要素" +
        "（OpenAI 兼容端点）；绝不回退 dsh 默认档。",
    );
  }
  const seg = segment as Record<string, unknown>;
  for (const key of ["provider", "baseURL", "apiKeyEnv"] as const) {
    if (typeof seg[key] !== "string" || (seg[key] as string).trim() === "") {
      throw new Error(
        `模型未显式配置：config.model.${key} 缺失或为空——fenixd provider 链渲染必须给出完整三要素` +
          `（provider/baseURL/apiKeyEnv/model），绝不回退 dsh 默认档。`,
      );
    }
  }
  if (typeof seg.model !== "string" || seg.model.trim() === "") {
    throw new Error(
      "模型未显式配置：config.model.model 缺失或为空——模型必须显式指定，绝不回退 dsh 默认档" +
        "（铁律，承袭 narrative 网关别名事故）。",
    );
  }
  // 可选字段类型守卫：字段存在但形态非法即在校验期 fail-fast（缺省路径行为不变），
  // 避免异常值经 buildProviderSegment 原样透传进 dsh providers 配置、推迟到请求期才暴露。
  for (const key of ["contextWindow", "maxTokens"] as const) {
    const val = seg[key];
    if (val !== undefined && (typeof val !== "number" || !Number.isInteger(val) || val <= 0)) {
      throw new Error(
        `模型未显式配置：config.model.${key} 必须是正整数——当前值类型 ${typeof val}（${String(val)}）非法。`,
      );
    }
  }
  const headers = seg.headers;
  if (headers !== undefined) {
    if (typeof headers !== "object" || headers === null || Array.isArray(headers)) {
      throw new Error(
        `模型未显式配置：config.model.headers 必须是 string→string 的纯对象——当前值类型 ` +
          `${Array.isArray(headers) ? "array" : typeof headers} 非法。`,
      );
    }
    for (const [headerKey, headerVal] of Object.entries(headers)) {
      if (typeof headerVal !== "string") {
        throw new Error(
          `模型未显式配置：config.model.headers.${headerKey} 的值必须是字符串——当前值类型 ${typeof headerVal}（${String(headerVal)}）非法。`,
        );
      }
    }
  }
  return segment as unknown as FenixModelSegment;
}

/** 构造 llm-pi-ai 的 providers 配置段（OpenAI 兼容端点路由）。 */
export function buildProviderSegment(seg: FenixModelSegment): Record<string, unknown> {
  return {
    [seg.provider]: {
      displayName: seg.provider,
      api: seg.api ?? "openai-completions",
      baseURL: seg.baseURL,
      apiKeyEnv: seg.apiKeyEnv,
      ...(seg.headers ? { headers: seg.headers } : {}),
      models: [
        {
          id: seg.model,
          name: seg.model,
          contextWindow: seg.contextWindow ?? DEFAULT_MODEL_CONTEXT_WINDOW,
          maxTokens: seg.maxTokens ?? DEFAULT_MODEL_MAX_TOKENS,
          input: ["text"],
        },
      ],
    },
  };
}

/** 构造 agent-default-model 的配置段。 */
export function buildDefaultModelSegment(seg: FenixModelSegment): { provider: string; model: string } {
  return { provider: seg.provider, model: seg.model };
}

/** 由 config.model 构造 fenixModelConfig 服务对象（校验失败即抛错）。 */
export function createModelConfigService(config: unknown): {
  providers: Record<string, unknown>;
  provider: string;
  model: string;
} {
  const seg = assertModelExplicit((config as { model?: unknown })?.model);
  return {
    providers: buildProviderSegment(seg),
    ...buildDefaultModelSegment(seg),
  };
}

// ── dsh 装配：fenix-model-config 插件 ──────────────────────────────────────

export const name = "fenix-model-config";

/**
 * 插件入口：校验版本钉扎与模型三要素，provide `fenixModelConfig` 服务供
 * llm-pi-ai / agent-default-model / headless-runner 经 inject + !!js 取值。
 * 无 Config schema（cordis 原样传 config）——三要素校验由 assertModelExplicit
 * 以确切中文错误信息执行，缺失即 fail-fast。
 */
export function apply(ctx: { reflect: { provide(name: string, value: unknown): unknown } }, config: unknown): void {
  assertDshPinned();
  const service = createModelConfigService(config);
  ctx.reflect.provide("fenixModelConfig", service);
}
