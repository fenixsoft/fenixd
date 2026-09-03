import { Button, Card, Form, Input, Switch, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

// 前端 HH:MM 校验（00:00–23:59），与后端 ConfigLoader.is_valid_hhmm 同格式语义
// （add-daily-self-review「非法输入双端拒绝」）。
const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

interface SelfReviewPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function SelfReviewPanel({ config, onSave }: SelfReviewPanelProps) {
  const [form] = Form.useForm();

  const initial = {
    enabled: config.self_review?.enabled ?? false,
    run_at: config.self_review?.run_at ?? '22:00',
    read_todo: config.self_review?.read_todo ?? false,
  };

  useEffect(() => {
    form.setFieldsValue(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.self_review, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        self_review: {
          enabled: values.enabled,
          run_at: values.run_at,
          read_todo: values.read_todo,
        },
      });
    } catch {
      // 校验失败：antd 已在表单内渲染 explain-error 提示，无需额外日志
    }
  };

  return (
    <div>
      <h3>每日自省</h3>
      <Text type="secondary">
        daemon 每晚在指定时间由 Administrator Agent 自动执行当日工作回顾（浪费 /
        失误 / 可改进），结果追加写入项目根 todo.md 并自动提交。enabled=false
        时全链路零动作。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} initialValues={initial} layout="vertical">
          <Form.Item
            name="enabled"
            label={
              <>
                启用每日自省<span className="label-note">（admin.self_review.enabled）</span>
              </>
            }
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Text type="secondary">缺省关闭。开启后于次日 run_at 时间点生效（错过后启动补跑）。</Text>

          <Form.Item
            name="run_at"
            label={
              <>
                每日执行时间<span className="label-note">（admin.self_review.run_at，HH:MM）</span>
              </>
            }
            style={{ marginTop: 24 }}
            rules={[
              { required: true, message: '请输入执行时间' },
              {
                pattern: HHMM_RE,
                message: '时间格式必须为 HH:MM（00:00–23:59），如 22:00',
              },
            ]}
          >
            <Input placeholder="22:00" maxLength={5} style={{ width: 160 }} />
          </Form.Item>
          <Text type="secondary">缺省 22:00。实际触发时刻为 run_at 后的第一个巡检周期。</Text>

          <Form.Item
            name="read_todo"
            label={
              <>
                注入既有 todo.md 上下文<span className="label-note">（admin.self_review.read_todo）</span>
              </>
            }
            valuePropName="checked"
            style={{ marginTop: 24 }}
          >
            <Switch />
          </Form.Item>
          <Text type="secondary">
            开启时把项目根 todo.md 全文注入自省 prompt，供 Agent 识别历史条目、
            避免重复并标注已闭环项。缺省关闭。
          </Text>
        </Form>
      </Card>
      <div style={{ textAlign: 'right', marginTop: 24 }}>
        <Button type="primary" onClick={handleSave} data-testid="self-review-save">
          保 存
        </Button>
      </div>
    </div>
  );
}
