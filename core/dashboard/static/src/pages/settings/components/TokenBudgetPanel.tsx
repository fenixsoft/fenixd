import { Button, Card, Form, InputNumber, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface TokenBudgetPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function TokenBudgetPanel({ config, onSave }: TokenBudgetPanelProps) {
  const [form] = Form.useForm();

  const initialValues = {
    token_budget_millions: config.agents.token_budget_millions ?? 50,
    daily_run_limit: config.agents.daily_run_limit ?? 50,
    impl_run_budget: config.agents.impl_run_budget ?? 6,
    verify_redo_budget: config.agents.verify_redo_budget ?? 3,
  };

  useEffect(() => {
    form.setFieldsValue({
      token_budget_millions: config.agents.token_budget_millions ?? 50,
      daily_run_limit: config.agents.daily_run_limit ?? 50,
      impl_run_budget: config.agents.impl_run_budget ?? 6,
      verify_redo_budget: config.agents.verify_redo_budget ?? 3,
    });
  }, [config.agents, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        agents: {
          token_budget_millions: values.token_budget_millions,
          daily_run_limit: values.daily_run_limit,
          impl_run_budget: values.impl_run_budget,
          verify_redo_budget: values.verify_redo_budget,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>预算</h3>
      <Text type="secondary">Token 预算、每日 Agent 运行限额与实现尝试预算等成本控制项。</Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} initialValues={initialValues} layout="vertical">
          <Form.Item
            name="token_budget_millions"
            label={
              <>
                Token 预算<span className="label-note">（百万，0=关闭）</span>
              </>
            }
            rules={[{ required: true, message: '请输入 Token 预算' }]}
          >
            <InputNumber min={0} max={1000} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 50（百万 input token）。保存后约 30 秒内热加载生效；设为 0 表示关闭预算检查。单 SPEC 累计 input token 达到 80% 发提醒级告警、达到 100% 发升级级告警，不自动冻结，由人工决定是否处置。
          </Text>

          <Form.Item
            name="daily_run_limit"
            label={
              <>
                每日 Agent 运行限额<span className="label-note">（agents.daily_run_limit，0 = 不限）</span>
              </>
            }
            rules={[{ required: true, message: '请输入每日运行限额' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={0} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 50。单个 UTC 自然日内所有 Agent 类型成功运行的累计上限（实现/验证/管理共用一个池），达到后当日停止派发，UTC 次日 0 点自动归零。设为 0 表示不限制。
          </Text>

          <Form.Item
            name="impl_run_budget"
            label={
              <>
                实现尝试预算<span className="label-note">（agents.impl_run_budget，1-10）</span>
              </>
            }
            rules={[{ required: true, message: '请输入实现尝试预算' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 4。每 SPEC 跨修复周期的实现 run 启动次数上限（含首次实现与每轮修复重派）。达到上限即冻结该 SPEC 并交人工裁决，需人工调大预算或推进状态。合法范围 1-10。
          </Text>

          <Form.Item
            name="verify_redo_budget"
            label={
              <>
                重启重验预算<span className="label-note">（agents.verify_redo_budget，1-10）</span>
              </>
            }
            rules={[{ required: true, message: '请输入重启重验预算' }]}
            style={{ marginTop: 24 }}
          >
            <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 3。daemon 重启恢复路径（testing → implemented 重派 verify）的累计重验次数上限。达上限即冻结该 SPEC 并交人工裁决（人工解冻后计数清零），防止「毒 SPEC 借反复重启无限重验」烧 token。合法范围 1-10。
          </Text>
        </Form>
      </Card>
      <div style={{ textAlign: 'right', marginTop: 24 }}>
        <Button type="primary" onClick={handleSave}>
          保存
        </Button>
      </div>
    </div>
  );
}
