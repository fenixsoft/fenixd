import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import { getArbiterStatus } from '@/services/dashboard';
import type { ArbiterStatus } from '@/services/dashboard';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';

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
  /** 父级 index.handleSave（返回 Promise<boolean>），与 useGatedFormPanel
   *  onSave 契约同型（Promise<boolean | void>）。 */
  onSave: (values: Partial<ConfigData>) => Promise<boolean | void>;
  /** 项目名（项目级作用域下取运行时状态；用户级不传） */
  project?: string;
}

// Arbiter 全局决策者车道设置面板（add-arbiter-lane 5.3）：四键配置 + 运行时
// 状态只读摘要（队列/台账）。保存走既有配置写回通道（index.handleSave →
// saveConfig → write_config 前置校验 + 白名单合并），回显当前生效值（后端经
// get_arbiter_config 归一，非法值回显缺省）。
export default function ArbiterPanel({ config, onSave, project }: ArbiterPanelProps) {
  const [form] = Form.useForm();
  const { setDirty } = usePanelDirty();
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildArbiterFormValues(config.arbiter),
    backfillDeps: [config.arbiter],
    onSave,
    buildPayload: (values): Partial<ConfigData> => ({
      arbiter: {
        enabled: values.enabled,
        budget_wallclock_s: values.budget_wallclock_s,
        budget_tokens: values.budget_tokens,
        max_consecutive_failures: values.max_consecutive_failures,
      },
    }),
  });

  // 运行时状态只读摘要（恒 200 自含端点，失败静默为空态——非关键数据）
  const [status, setStatus] = useState<ArbiterStatus | null>(null);
  const loadStatus = useCallback(async () => {
    if (!project) return;
    try {
      setStatus(await getArbiterStatus(project));
    } catch {
      setStatus(null);
    }
  }, [project]);
  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const ledger = status?.ledger;

  return (
    <div data-testid="arbiter-panel">
      <h3>全局决策者（Arbiter）</h3>
      <Text type="secondary">
        冻结/升级事件自动唤起的全局决策者车道：跨车道取证调查，白名单内自主处置
        （处置成功原告警直接终态化、零用户可感知），白名单外/处置失败/连败/预算
        耗尽产裁决包升级人工。权限边界为提示词红线 + 处置台账审计（.fenix/
        arbiter_ledger.jsonl 五段结构）。
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
              启用全局决策者车道
              <span className="label-note">（arbiter.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            缺省开启。关闭后冻结/升级边走既有 narrative + 人工路径——不派发、
            不落台账、不改告警形态，全部行为与引入本车道之前完全一致（关闭态
            零侵扰）。
          </Text>

          <Form.Item
            name="budget_wallclock_s"
            label={
              <>
                单次调查墙钟预算
                <span className="label-note">（arbiter.budget_wallclock_s）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: '请输入墙钟预算' },
              { type: 'integer', min: 1, message: '须为正整数秒' },
            ]}
            data-testid="arbiter-field-budget_wallclock_s"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter="秒" />
          </Form.Item>
          <Text type="secondary">
            缺省 {ARBITER_DEFAULTS.budget_wallclock_s} 秒。调查 run 超时按本预算
            封顶；超限 → run 终止 → 半成品调查包升级人工（不静默死亡）。
          </Text>

          <Form.Item
            name="budget_tokens"
            label={
              <>
                单次调查 token 预算
                <span className="label-note">（arbiter.budget_tokens）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: '请输入 token 预算' },
              { type: 'integer', min: 1, message: '须为正整数' },
            ]}
            data-testid="arbiter-field-budget_tokens"
          >
            <InputNumber precision={0} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            缺省 {ARBITER_TOKENS_DEFAULT_TEXT}。按 usage 四键累计事后记账；超限 →
            停止自主尝试、半成品调查包升级人工。
          </Text>

          <Form.Item
            name="max_consecutive_failures"
            label={
              <>
                连败死人开关阈值
                <span className="label-note">
                  （arbiter.max_consecutive_failures）
                </span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: '请输入连败阈值' },
              { type: 'integer', min: 1, message: '须为正整数' },
            ]}
            data-testid="arbiter-field-max_consecutive_failures"
          >
            <InputNumber precision={0} style={{ width: '100%' }} addonAfter="次" />
          </Form.Item>
          <Text type="secondary">
            缺省 {ARBITER_DEFAULTS.max_consecutive_failures} 次。同 spec 同失败
            签名连续失败达本次数后停止自主尝试，半成品调查包升级人工。
          </Text>
        </Card>
      </Form>

      {project && (
        <Card style={{ marginTop: 12 }} data-testid="arbiter-status-card">
          <h4 style={{ marginTop: 0 }}>运行时状态（只读）</h4>
          {ledger ? (
            <Text type="secondary">
              处置台账共 {ledger.total ?? 0} 条
              {ledger.kinds && Object.keys(ledger.kinds).length > 0
                ? `（${Object.entries(ledger.kinds)
                    .map(([k, n]) => `${k}×${n}`)
                    .join('、')}）`
                : ''}
              ；队列深度 {status?.lane?.queue_depth ?? 0}，在飞签名{' '}
              {status?.lane?.active_signatures?.length ?? 0} 个。
            </Text>
          ) : (
            <Text type="secondary">—（运行时状态不可得）</Text>
          )}
        </Card>
      )}

      <div style={SETTINGS_ACTIONS_ROW_STYLE}>
        <Button
          type="primary"
          onClick={handleSave}
          loading={saving}
          disabled={saving}
          data-testid="arbiter-save"
        >
          保存
        </Button>
      </div>
    </div>
  );
}
