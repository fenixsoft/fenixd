// 文案经 useIntl（i18n 修复轮 batch-S：本文件静态中文文案迁 i18n 目录）
import { useIntl } from '@umijs/max';
import { Card, Form, InputNumber, Switch, Typography } from 'antd';
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import { getArbiterStatus } from '@/services/dashboard';
import type { ArbiterStatus } from '@/services/dashboard';
import { usePanelDirty } from '../panelDirty';
import type { SettingsSectionHandle } from './settingsSection';

const { Text } = Typography;

// add-arbiter-lane：arbiter 配置节缺省与 ConfigLoader.get_arbiter_config 缺省
// 一致（enabled=true / budget_wallclock_s=1800 / budget_tokens=1000000 /
// max_consecutive_failures=2）。
const ARBITER_DEFAULTS = {
  enabled: true,
  budget_wallclock_s: 1800,
  budget_tokens: 1000000,
  max_consecutive_failures: 2,
};

// budget_tokens 缺省展示文案由数值派生（千分位），避免与 ARBITER_DEFAULTS
// 双份字面量漏改分叉。
const ARBITER_TOKENS_DEFAULT_TEXT =
  ARBITER_DEFAULTS.budget_tokens.toLocaleString('en-US');

// 四键表单映射单源（config 取值 ?? 缺省）：initialValues 与回填 effect 共用
// （BranchGcPanel 同款范式，避免两份映射漏改一处导致初值与回填值分叉）
function buildArbiterFormValues(cfg: ConfigData['arbiter'] | undefined) {
  return {
    enabled: cfg?.enabled ?? ARBITER_DEFAULTS.enabled,
    budget_wallclock_s:
      cfg?.budget_wallclock_s ?? ARBITER_DEFAULTS.budget_wallclock_s,
    budget_tokens: cfg?.budget_tokens ?? ARBITER_DEFAULTS.budget_tokens,
    max_consecutive_failures:
      cfg?.max_consecutive_failures ?? ARBITER_DEFAULTS.max_consecutive_failures,
  };
}

interface ArbiterPanelProps {
  config: ConfigData;
  /** 项目名（项目级作用域下取运行时状态；用户级不传） */
  project?: string;
}

// Arbiter 全局决策者车道设置面板（add-arbiter-lane 5.3）：四键配置 + 运行时
// 状态只读摘要（队列/台账）。配置写回走页签唯一保存按钮（StaleCodeSelfhealPanel
// 同款 collect 句柄模式，2026-11-05 用户指令「仲裁页签只留最下一个保存按钮」
// ——原面板自带保存钮与堆叠下方的 ChainPanel 保存钮并存），本面板经 ref 暴露
// collect() 由父页签校验并合并提交；表单回显维持回填门控（后端经
// get_arbiter_config 归一，非法值回显缺省）。
const ArbiterPanel = forwardRef<SettingsSectionHandle, ArbiterPanelProps>(
  function ArbiterPanel({ config, project }, ref) {
  const intl = useIntl();
  const [form] = Form.useForm();
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();

  const initialValues = buildArbiterFormValues(config.arbiter);

  // 回填门控（比照 StaleCodeSelfhealPanel cbec8303669f 同族面板）：无条件
  // setFieldsValue 会在保存往返或父级 setConfig 刷新 config 时覆盖用户尚未
  // 保存的输入。对回填产物做序列化比较，只在内容真变化时回填。
  const lastBackfillRef = useRef('');
  useEffect(() => {
    const next = buildArbiterFormValues(config.arbiter);
    const key = JSON.stringify(next);
    if (key === lastBackfillRef.current) return;
    form.setFieldsValue(next);
    // ref 记账在回填成功之后（与 useGatedFormPanel item 51e106646c29 对齐）：
    // setFieldsValue 抛异常时 key 不落 ref，同样的配置内容依赖下次变化仍会重试
    lastBackfillRef.current = key;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.arbiter, form]);

  // 页签唯一保存入口的收集句柄：校验通过返回本节补丁，失败返回 null
  // （antd 已在表单内渲染 explain-error，静默返回不落 console）
  useImperativeHandle(
    ref,
    () => ({
      collect: async () => {
        try {
          const values = await form.validateFields();
          return {
            arbiter: {
              enabled: values.enabled,
              budget_wallclock_s: values.budget_wallclock_s,
              budget_tokens: values.budget_tokens,
              max_consecutive_failures: values.max_consecutive_failures,
            },
          };
        } catch {
          return null;
        }
      },
    }),
    [form],
  );

  // 运行时状态只读摘要（恒 200 自含端点，失败静默为空态——非关键数据）
  const [status, setStatus] = useState<ArbiterStatus | null>(null);
  // 过期响应守卫（code-review item 11b113c23fe1，比照 QualityPanel 的 effect
  // alive 口径）：loadStatus 由 useCallback([project]) 驱动、effect 随之重跑，
  // 仅凭依赖链挡不住「旧项目请求后到」——项目 A 的响应慢于项目 B 时，A 的
  // 处置台账/队列数据会覆盖 B 的「运行时状态（只读）」卡片。effect 挂 per-effect
  // alive（cleanup 置 false）并经判活回调传入 loadStatus，写 status 前判活，
  // 被项目切换取代/已卸载实例的响应一律丢弃；不传回调的调用语义不变。
  const loadStatus = useCallback(async (isStale?: () => boolean) => {
    if (!project) return;
    try {
      const next = await getArbiterStatus(project);
      if (isStale?.()) return;
      setStatus(next);
    } catch {
      if (isStale?.()) return;
      setStatus(null);
    }
  }, [project]);
  useEffect(() => {
    let alive = true;
    void loadStatus(() => !alive);
    return () => {
      alive = false;
    };
  }, [loadStatus]);

  const ledger = status?.ledger;

  return (
    <div data-testid="arbiter-panel">
      <h3>{intl.formatMessage({ id: 'settings.arbiter.title' })}</h3>
      <Text type="secondary">
        {intl.formatMessage({ id: 'settings.arbiter.desc' })}
      </Text>
      <Form
        form={form}
        initialValues={initialValues}
        layout="vertical"
        onValuesChange={() => setDirty(true)}
      >
        <Card style={{ marginTop: 12 }}>
          <div className="switch-inline-row">
            <Form.Item name="enabled" valuePropName="checked" noStyle>
              <Switch data-testid="arbiter-control-enabled" />
            </Form.Item>
            <span className="switch-inline-label">
              {intl.formatMessage({ id: 'settings.arbiter.enabledSwitch' })}
              <span className="label-note">（arbiter.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            {intl.formatMessage({ id: 'settings.arbiter.enabledDesc' })}
          </Text>

          <Form.Item
            name="budget_wallclock_s"
            label={
              <>
                {intl.formatMessage({ id: 'settings.arbiter.wallclock.label' })}
                <span className="label-note">（arbiter.budget_wallclock_s）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.arbiter.wallclock.required' }) },
              { type: 'integer', min: 1, message: intl.formatMessage({ id: 'settings.arbiter.integerSeconds' }) },
            ]}
            data-testid="arbiter-field-budget_wallclock_s"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.arbiter.unit.seconds' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage(
              { id: 'settings.arbiter.wallclock.desc' },
              { seconds: ARBITER_DEFAULTS.budget_wallclock_s },
            )}
          </Text>

          <Form.Item
            name="budget_tokens"
            label={
              <>
                {intl.formatMessage({ id: 'settings.arbiter.tokens.label' })}
                <span className="label-note">（arbiter.budget_tokens）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.arbiter.tokens.required' }) },
              { type: 'integer', min: 1, message: intl.formatMessage({ id: 'settings.arbiter.integer' }) },
            ]}
            data-testid="arbiter-field-budget_tokens"
          >
            <InputNumber precision={0} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage(
              { id: 'settings.arbiter.tokens.desc' },
              { count: ARBITER_TOKENS_DEFAULT_TEXT },
            )}
          </Text>

          <Form.Item
            name="max_consecutive_failures"
            label={
              <>
                {intl.formatMessage({ id: 'settings.arbiter.failures.label' })}
                <span className="label-note">
                  （arbiter.max_consecutive_failures）
                </span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: intl.formatMessage({ id: 'settings.arbiter.failures.required' }) },
              { type: 'integer', min: 1, message: intl.formatMessage({ id: 'settings.arbiter.integer' }) },
            ]}
            data-testid="arbiter-field-max_consecutive_failures"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter={intl.formatMessage({ id: 'settings.arbiter.unit.times' })} />
          </Form.Item>
          <Text type="secondary">
            {intl.formatMessage(
              { id: 'settings.arbiter.failures.desc' },
              { count: ARBITER_DEFAULTS.max_consecutive_failures },
            )}
          </Text>
        </Card>
      </Form>

      {project && (
        <Card style={{ marginTop: 12 }} data-testid="arbiter-status-card">
          <h4 style={{ marginTop: 0 }}>{intl.formatMessage({ id: 'settings.arbiter.status.title' })}</h4>
          {ledger ? (
            <Text type="secondary">
              {intl.formatMessage({ id: 'settings.arbiter.status.ledger' }, { count: ledger.total ?? 0 })}
              {ledger.kinds && Object.keys(ledger.kinds).length > 0
                ? intl.formatMessage(
                    { id: 'settings.arbiter.status.kinds' },
                    {
                      kinds: Object.entries(ledger.kinds)
                        .map(([k, n]) => `${k}×${n}`)
                        .join('、'),
                    },
                  )
                : ''}
              {intl.formatMessage(
                { id: 'settings.arbiter.status.tail' },
                { queue: status?.lane?.queue_depth ?? 0, active: status?.lane?.active_signatures?.length ?? 0 },
              )}
            </Text>
          ) : (
            <Text type="secondary">{intl.formatMessage({ id: 'settings.arbiter.status.unavailable' })}</Text>
          )}
        </Card>
      )}
    </div>
  );
  },
);

export default ArbiterPanel;
