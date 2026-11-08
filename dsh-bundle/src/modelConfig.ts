/**
 * modelConfig.ts — 模型显式配置契约（OpenAI 兼容端点三要素）。
 *
 * 设计决策 4：模型配置采用「配置文件渲染」而非 env 传递——SPEC-3 的 dsh_adapter
 * 把 fenixd provider 链（name/baseurl/apikey/model）渲染为本插件 config 的 model
 * 段；本插件启动时按形态划界处置（add-dispatch-precheck-true-fallback D1，
 * 2026-11-08 用户裁定 dsh+fenix 走真对称回落）：
 * - config.model 整体缺席（键不存在 / 无 config）→ 回落形态（mode: "fallback"），
 *   agent-default-model 由 dsh-base 原生默认档配置供数（真对称回落，零硬编码），
 *   插件跳过显式覆盖并 WARN 留痕；
 * - config.model 在场但残缺（null/空串/缺要素对象）→ 保持「模型未显式配置」
 *   fail-fast（笔误防护，承袭 narrative 网关别名事故：部分链不是回落理由）。
 *
 * 渲染产物：
 * - providers —— 挂到 dsh-base 的 llm-pi-ai 条目 config.providers
 *   （OpenAI 兼容端点：api=openai-completions + baseURL + apiKeyEnv + models 目录）；
 * - provider / model —— 挂到 agent-default-model 条目，指定默认路由与模型。
 *
 * fail-fast 通道：残缺形态校验失败在本插件 apply 内抛错 → fenixModelConfig
 * 服务缺失 → 依赖它的 llm-pi-ai / agent-default-model / headless-runner（dsh
 * required 启动条目，cordis.patch.yml 已追加注入）一起失败 → StartupError
 * exit 1。回落形态服务恒提供（headless-runner 正常激活），两行
 * agent-default-model 以互补 disabled 切换供数通道（见 cordis.patch.yml）。
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

/**
 * 校验 model 段显式存在且三要素齐备；残缺形态抛「模型未显式配置」。
 *
 * 形态划界：``undefined``（config.model 整体缺席）返回 ``null`` 作为回落形态
 * 标记——agent-default-model 由 dsh-base 原生默认档配置供数（真对称回落）；
 * ``null``/空串/缺要素对象属显式在场但残缺的笔误形态，保持 fail-fast 不走回落。
 */
export function assertModelExplicit(segment: unknown): FenixModelSegment | null {
  if (segment === undefined) {
    return null;
  }
  if (typeof segment !== "object" || segment === null || Array.isArray(segment)) {
    throw new Error(
      "模型未显式配置：fenix-dsh-bundle 要求 config.model 显式给出 OpenAI 兼容端点三要素" +
        "（provider/baseURL/apiKeyEnv）与模型 id（model）；绝不回退 dsh 默认档。",
    );
  }
  const seg = segment as Record<string, unknown>;
  for (const key of ["provider", "baseURL", "apiKeyEnv"] as const) {
    if (typeof seg[key] !== "string" || (seg[key] as string).trim() === "") {
      throw new Error(
        `模型未显式配置：config.model.${key} 缺失或为空——fenixd provider 链渲染必须给出完整端点三要素` +
          `（provider/baseURL/apiKeyEnv）与模型 id（model），绝不回退 dsh 默认档。`,
      );
    }
  }
  if (typeof seg.model !== "string" || seg.model.trim() === "") {
    throw new Error(
      "模型未显式配置：config.model.model 缺失或为空——模型必须显式指定，绝不回退 dsh 默认档" +
        "（铁律，承袭 narrative 网关别名事故）。",
    );
  }
  // baseURL 形态守卫（与下方可选字段守卫同型，收口在校验期）：缺 scheme
  // （如 "127.0.0.1:18787/v1"）或含空格等畸形值若放行，会经 buildProviderSegment
  // 原样透传进 providers 配置、首个 LLM 请求期才失败——定位成本远高于启动期拦截。
  // 校验与透传同用 trim 后的值：WHATWG URL 解析会剥离入参首尾空白（及内嵌
  // tab/LF/CR），若仍按原值透传，校验基于规范化形态而下游拿到未规范化原值，
  // 带空白端点会推迟到首个 LLM 请求期才暴露。
  const normalizedBaseURL = (seg.baseURL as string).trim();
  let parsedBaseURL: URL;
  try {
    parsedBaseURL = new URL(normalizedBaseURL);
  } catch {
    throw new Error(
      `模型配置非法：config.model.baseURL 必须是可解析的 http(s) URL——当前值「${seg.baseURL}」无法解析为 URL。`,
    );
  }
  if (parsedBaseURL.protocol !== "http:" && parsedBaseURL.protocol !== "https:") {
    throw new Error(
      `模型配置非法：config.model.baseURL 的协议必须是 http/https——当前值「${seg.baseURL}」协议为 ${parsedBaseURL.protocol} 非法。`,
    );
  }
  // 可选字段类型守卫：字段存在但形态非法即在校验期 fail-fast（缺省路径行为不变），
  // 避免异常值经 buildProviderSegment 原样透传进 dsh providers 配置、推迟到请求期才暴露。
  for (const key of ["contextWindow", "maxTokens"] as const) {
    const val = seg[key];
    if (val !== undefined && (typeof val !== "number" || !Number.isInteger(val) || val <= 0)) {
      throw new Error(
        `模型配置非法：config.model.${key} 必须是正整数——当前值类型 ${typeof val}（${String(val)}）非法。`,
      );
    }
  }
  const api = seg.api;
  if (api !== undefined && typeof api !== "string") {
    throw new Error(
      `模型配置非法：config.model.api 必须是字符串（线协议名，如 openai-completions）——` +
        `当前值类型 ${typeof api}（${String(api)}）非法。`,
    );
  }
  const headers = seg.headers;
  if (headers !== undefined) {
    if (typeof headers !== "object" || headers === null || Array.isArray(headers)) {
      throw new Error(
        `模型配置非法：config.model.headers 必须是 string→string 的纯对象——当前值类型 ` +
          `${Array.isArray(headers) ? "array" : typeof headers} 非法。`,
      );
    }
    for (const [headerKey, headerVal] of Object.entries(headers)) {
      if (typeof headerVal !== "string") {
        throw new Error(
          `模型配置非法：config.model.headers.${headerKey} 的值必须是字符串——当前值类型 ${typeof headerVal}（${String(headerVal)}）非法。`,
        );
      }
    }
  }
  // 三要素以 trim 后的规范化值返回（校验值 == 透传值）：provider/apiKeyEnv 同样
  // 只按 trim 判空，原样透传会把带空白形态带进 providers 配置与 agent-default-model
  // 路由；其余字段（model/api/headers 等）保持原样。
  return {
    ...seg,
    provider: (seg.provider as string).trim(),
    baseURL: normalizedBaseURL,
    apiKeyEnv: (seg.apiKeyEnv as string).trim(),
  } as unknown as FenixModelSegment;
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

/** fenixModelConfig 服务形态：显式链（三要素渲染产物）或回落（整体缺席）。 */
export type FenixModelConfigService =
  | {
      mode: "explicit";
      providers: Record<string, unknown>;
      provider: string;
      model: string;
    }
  | { mode: "fallback" };

/**
 * 由 config.model 构造 fenixModelConfig 服务对象。
 * config.model 整体缺席（含 config 本身缺席）→ 回落形态服务；残缺形态抛错。
 */
export function createModelConfigService(config: unknown): FenixModelConfigService {
  const seg = assertModelExplicit((config as { model?: unknown } | undefined)?.model);
  if (seg === null) {
    return { mode: "fallback" };
  }
  return {
    mode: "explicit",
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
 * 以确切中文错误信息执行；config.model 整体缺席时提供回落形态服务并 WARN
 * 留痕（agent-default-model 由 dsh-base 原生配置供数，cordis.patch.yml 双行
 * 互补 disabled 装配），残缺形态仍 fail-fast（服务缺失 → StartupError）。
 */
export function apply(
  ctx: {
    reflect: { provide(name: string, value: unknown): unknown };
    logger?: { warn(message: string, ...args: unknown[]): void };
  },
  config: unknown,
): void {
  assertDshPinned();
  const service = createModelConfigService(config);
  if (service.mode === "fallback") {
    ctx.logger?.warn(
      "fenix-model-config: config.model 缺席，回落 dsh 默认档" +
        "（无分配 provider 链的对称回落形态：agent-default-model 由 dsh-base 原生配置供数）",
    );
  }
  ctx.reflect.provide("fenixModelConfig", service);
}
