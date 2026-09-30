// 设置面板表单脚手架公共 hook（code-review item 5c5a259b8443）。
// SystemPanel / LlmProviderPanel / MiscSettingsPanel / AgentModelPanel /
// QualityPanel / TokenBudgetPanel 六个面板此前各自复制同一套流程——
// buildXxxFormValues 单源映射、lastBackfillRef 序列化比较回填门控、savingRef
// 重入守卫、「校验与持久化分离」的 handleSave——逐份修补已产生口径漂移
// （重入守卫一度 savingRef 与仅 state 两种形态并存）。收敛为单个 hook 后，
// 各面板只保留字段映射（buildValues / buildPayload）与校验规则（表单 rules +
// checkValues），流程语义与各面板原实现逐点等价。
import { message } from 'antd';
import type { FormInstance } from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';

export interface GatedFormPanelOptions<TValues> {
  /** 面板 <Form> 的实例（Form.useForm 产物） */
  form: FormInstance<TValues>;
  /** 单源表单值构建：initialValues 与回填门控共用（面板提供字段映射，config 取值 ?? 缺省） */
  buildValues: () => TValues;
  /** 回填 effect 依赖的面板 config 段（form 由 hook 自动追加，依赖清单与各面板原实现一致） */
  backfillDeps: readonly unknown[];
  /** 校验通过后组装保存载荷（面板字段映射；payload 构建与 onSave 同 try，构建异常也走保存失败反馈） */
  buildPayload: (values: TValues) => Partial<ConfigData>;
  /** 持久化入口（父级 index.handleSave）；resolve(false) = 保存失败已由父级提示，hook 不重复 toast */
  onSave: (payload: Partial<ConfigData>) => Promise<boolean | void>;
  /** 校验前的面板专属拦截（价格行裁剪 / 重复键检查等）：返回 false = 已提示并中止本次保存 */
  beforeValidate?: () => boolean | void;
  /** 校验通过后、持久化前的面板专属校验（如角色链可用模型检查）：返回错误文案 = 判定失败并中止 */
  checkValues?: (values: TValues) => string | void;
  /** 校验失败回调（antd 已在表单内渲染 explain-error；如 LlmProviderPanel 借此展开折叠区） */
  onValidateError?: () => void;
  /**
   * 回填定制（缺省直接 setFieldsValue）。apply() 内部才真正写入表单：需要
   * 在写入前读取旧值（如 LlmProviderPanel 回填前取当前行身份串清理健康徽标
   * 缓存）的面板在 apply 前后插入自身逻辑。
   */
  onBackfill?: (next: TValues, apply: () => void) => void;
}

export function useGatedFormPanel<TValues>(options: GatedFormPanelOptions<TValues>) {
  const {
    form,
    buildValues,
    backfillDeps,
    onSave,
    buildPayload,
    beforeValidate,
    checkValues,
    onValidateError,
    onBackfill,
  } = options;
  // 保存重入守卫（各面板原 8ccf20511320 / 53b14fb31196 / fe84991f84a0 /
  // bbc939741560 / d0faa2345d54 / 66e48a34144b 同族条目）：onSave 是异步，
  // 提交期间连点会发出重叠的 saveConfig 请求（并发写同一配置文件，落盘结果
  // 取决于到达顺序）——saving 期间按钮置 loading/disabled 并在入口短路；
  // setSaving 渲染生效存在 React 调度间隙，经 savingRef 写读同帧原子拦住
  // 连点，state 只负责按钮视觉反馈。
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);

  // 首帧初值与回填共用 buildValues 单源：<Form initialValues> 首帧直出真实
  // 配置，不等回填 effect（消除一帧空显闪变）。antd 只在挂载时消费
  // initialValues，useState 惰性初始化（传函数引用，非调用结果）让 buildValues
  // 仅首帧执行一次，后续渲染不再白算。
  const [initialValues] = useState(buildValues);

  // 回填门控（各面板原 5be7cabc4d91 / 5d6582ba9951 / 0a2bd3f20fcd /
  // 9f98edec21fa / 241f4f2d452a / cbec8303669f 同族条目）：无条件
  // setFieldsValue 会在保存往返、「同步用户级设置」或其它面板保存触发的父级
  // setConfig 时，用外部值覆盖用户在请求在飞期间继续输入、尚未保存的内容。
  // 对 buildValues 产物做序列化比较，只在内容真变化时回填。
  const lastBackfillRef = useRef('');
  useEffect(() => {
    const next = buildValues();
    const key = JSON.stringify(next);
    if (key === lastBackfillRef.current) return;
    lastBackfillRef.current = key;
    if (onBackfill) {
      onBackfill(next, () => form.setFieldsValue(next));
    } else {
      form.setFieldsValue(next);
    }
    // 依赖由调用方按面板订阅的 config 段传入（长度逐面板恒定）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...backfillDeps, form]);

  const handleSave = async () => {
    if (savingRef.current) return;
    // 先置位再校验（QualityPanel item 2a72f9839b69 口径）：validateFields 是
    // 异步微任务，重入短路必须先于任何 await 落位。
    savingRef.current = true;
    setSaving(true);
    try {
      // 保存入口、校验前的面板专属拦截；false = 面板已给出提示，中止本次保存。
      // 回调自身意外异常与 onSave 同口径兜底（否则穿透 handleSave 成为按钮
      // onClick 的未处理拒绝，saving 复位后按钮恢复可点却无任何错误提示）。
      let skipped: boolean | void;
      try {
        skipped = beforeValidate?.();
      } catch (error) {
        message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
        return;
      }
      if (skipped === false) return;
      // 分离「表单校验」与「保存持久化」（各面板原 834f22222a24 / 25f889b81633
      // / 9125d4a7f7b4 / 3086b7e96c4f / def003cd8cff 同族条目）：校验失败 antd
      // 已在表单内渲染 explain-error 提示，静默返回（不落 console，避免触发
      // 验证的 no_console_error 断言）。
      let values: TValues;
      try {
        values = await form.validateFields();
      } catch {
        onValidateError?.();
        return;
      }
      // checkValues 意外异常同 onSave 兜底口径，不无声穿透 handleSave
      let invalid: string | void;
      try {
        invalid = checkValues?.(values);
      } catch (error) {
        message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
        return;
      }
      if (typeof invalid === 'string') {
        message.error(invalid);
        return;
      }
      try {
        const ok = await onSave(buildPayload(values));
        // ok === false：父级 handleSave 已 message.error 具体原因，此处不重复 toast
        if (ok === false) return;
      } catch (error) {
        // 持久化异常兜底：父级当前自带失败 toast 并以 resolve(false) 结束
        // （QualityPanel item 330164f11711：当前接线下子层观察不到拒绝），此
        // catch 保证父级反馈路径调整（onSave 不再自带 toast / 改为 reject）时
        // 保存失败不退化为无声失败
        message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return { saving, initialValues, handleSave };
}
