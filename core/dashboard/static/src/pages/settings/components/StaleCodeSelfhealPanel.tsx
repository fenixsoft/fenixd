// 文案经 useIntl（i18n 修复轮 batch-S：本文件静态中文文案迁 i18n 目录）
import { useIntl } from '@umijs/max';
import { Card, Form, InputNumber, Switch, Typography } from 'antd';
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import type { ConfigData } from '@/services/dashboard';
import type { SettingsSectionHandle } from './settingsSection';
import { usePanelDirty } from '../panelDirty';

const { Text } = Typography;

// add-stale-code-selfheal：陈旧自愈配置节缺省与 ConfigLoader 缺省一致
// （enabled=true / idle_confirm_seconds=600，evo-reduce-stale-code-selfheal-
// noise——原 120 会把开发日密集落地批次逐个放大成多轮重启）
const DEFAULT_IDLE_SECONDS = 600;
const MAX_IDLE_SECONDS = 86400;

// 两字段表单映射单源（config 取值 ?? 缺省）：initialValues 与回填 effect 共用，
// 避免两份映射漏改一处导致初值与回填值分叉
function buildScsFormValues(scs: ConfigData['stale_code_selfheal'] | undefined) {
  return {
    enabled: scs?.enabled ?? true,
    idle_confirm_seconds: scs?.idle_confirm_seconds ?? DEFAULT_IDLE_SECONDS,
  };
}

interface StaleCodeSelfhealPanelProps {
  config: ConfigData;
}

// 保存按钮已上提到自进化页签底部（全页唯一），本卡片经 ref 暴露 collect()，
// 由父页签在唯一点击事件里与「建议改进项」卡片一起校验并合并提交。
const StaleCodeSelfhealPanel = forwardRef<
  SettingsSectionHandle,
  StaleCodeSelfhealPanelProps
>(function StaleCodeSelfhealPanel({ config }, ref) {
  const intl = useIntl();
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
  const scs = config.stale_code_selfheal;

  const initialValues = buildScsFormValues(scs);

  // 回填门控（比照 TokenBudgetPanel cbec8303669f 等同族面板）：无条件
  // setFieldsValue 会在父级 setConfig 刷新 config 时覆盖用户尚未保存的输入。
  // 对回填产物做序列化比较，只在内容真变化时回填。
  const lastBackfillRef = useRef('');
  useEffect(() => {
    const next = buildScsFormValues(config.stale_code_selfheal);
    const key = JSON.stringify(next);
    if (key === lastBackfillRef.current) return;
    form.setFieldsValue(next);
    // ref 记账在回填成功之后（与 useGatedFormPanel item 51e106646c29 对齐）：
    // setFieldsValue 抛异常时 key 不落 ref，同样的配置内容依赖下次变化仍会重试
    lastBackfillRef.current = key;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.stale_code_selfheal, form]);

  useImperativeHandle(
    ref,
    () => ({
      collect: async () => {
        try {
          const values = await form.validateFields();
          return {
            stale_code_selfheal: {
              enabled: values.enabled,
              idle_confirm_seconds: values.idle_confirm_seconds,
            },
          };
        } catch {
          // 校验失败：antd 已在表单内渲染 explain-error 提示
          return null;
        }
      },
    }),
    [form],
  );

  return (
    <div data-testid="stale-code-selfheal-panel">
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
        <h3>{intl.formatMessage({ id: 'settings.scs.title' })}</h3>
        <Text type="secondary">
          {intl.formatMessage({ id: 'settings.scs.desc1a' })}
          <code>.fenix/restart_request</code>
          {intl.formatMessage({ id: 'settings.scs.desc1b' })}
        </Text>
        <Card style={{ marginTop: 12 }}>
          <div className="switch-inline-row">
            <Form.Item name="enabled" valuePropName="checked" noStyle>
              <Switch data-testid="stale-code-selfheal-control-enabled" />
            </Form.Item>
            <span className="switch-inline-label">
              {intl.formatMessage({ id: 'settings.scs.enabledSwitch' })}
              <span className="label-note">（stale_code_selfheal.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.scs.desc2a' })}
            <code>.fenix/restart_request</code>
            {intl.formatMessage({ id: 'settings.scs.desc2b' })}
          </Text>

          <Form.Item
            name="idle_confirm_seconds"
            label={
              <>
                {intl.formatMessage({ id: 'settings.scs.idle.label' })}
                <span className="label-note">（stale_code_selfheal.idle_confirm_seconds）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.scs.idle.required' }) },
              // 正整数校验与 MiscSettingsPanel auto_threshold 同口径：不能用
              // InputNumber 的 min/max 代替——blur 时会把越界值静默钳回边界，
              // 用户永远看不到非法输入被拦截的表单错误提示
              {
                type: 'integer',
                min: 1,
                max: MAX_IDLE_SECONDS,
                message: intl.formatMessage(
                  { id: 'settings.scs.idle.range' },
                  { max: MAX_IDLE_SECONDS },
                ),
              },
            ]}
            data-testid="stale-code-selfheal-field-idle_confirm_seconds"
          >
            <InputNumber
              precision={0}
              style={{ width: '100%' }}
              addonAfter={intl.formatMessage({ id: 'settings.scs.unit.seconds' })}
            />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage(
              { id: 'settings.scs.idle.desc' },
              { seconds: DEFAULT_IDLE_SECONDS },
            )}
          </Text>
        </Card>
      </Form>
    </div>
  );
});

export default StaleCodeSelfhealPanel;
