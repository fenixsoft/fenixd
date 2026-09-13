import { Button, Card, Form, Radio, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton, { SETTINGS_ACTIONS_ROW_STYLE } from './SyncFromUserButton';

const { Text } = Typography;

interface ApprovalModePanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function ApprovalModePanel({ config, onSave, project, onConfigSynced }: ApprovalModePanelProps) {
  const [form] = Form.useForm();

  useEffect(() => {
    // 确保字段有值，使用配置值或默认值
    form.setFieldsValue({
      promote_mode: config.gates.promote_mode || 'auto',
      approve_mode: config.gates.approve_mode || 'manual',
      spec_review_mode: config.gates.spec_review_mode || 'auto',
    });
  }, [config.gates.approve_mode, config.gates.promote_mode, config.gates.spec_review_mode, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      // add-spec-review-gate（task 5.2）：保存载荷 MUST 同时提交新键与既有
      // approve_mode/promote_mode——后端按 patch 整段合并，缺键会被 _deep_merge_managed
      // 视作「未提交」保留原值，但并发/双轨写入时整段覆盖有丢失既有设置的风险。
      await onSave({
        gates: {
          promote_mode: values.promote_mode,
          approve_mode: values.approve_mode,
          spec_review_mode: values.spec_review_mode,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>审批</h3>
      <Text type="secondary">
        草稿晋升（drafted → ready）与推送审批（done → push）行为。auto 推送模式将自动执行 git push 到远端，请谨慎使用。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form
          form={form}
          initialValues={{
            promote_mode: config.gates.promote_mode || 'auto',
            approve_mode: config.gates.approve_mode || 'manual',
            spec_review_mode: config.gates.spec_review_mode || 'auto',
          }}
          layout="vertical"
        >
          {/* 草稿晋升模式（add-draft-promotion-gate D5，值语义对齐 approve_mode） */}
          <Form.Item
            name="promote_mode"
            label={
              <>
                草稿晋升模式<span className="label-note">（gates.promote_mode）</span>
              </>
            }
            rules={[{ required: true, message: '请选择草稿晋升模式' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="manual">
                  <strong>manual</strong> — 人工审批
                  <div>
                    <Text type="secondary">
                      SPEC 停留在草稿态供人工阅读，确认后经 /fenix-ready、项目页按钮或 CLI 手动放行。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="auto">
                  <strong>auto</strong> — 自动晋升
                  <div>
                    <Text type="secondary">
                      SPEC 注册为草稿后立即自动晋升 ready 并进入调度。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          {/* SPEC 方案评审（add-spec-review-gate D2/D3/D11，置于草稿晋升相邻位置） */}
          <Form.Item
            name="spec_review_mode"
            label={
              <>
                SPEC 方案评审<span className="label-note">（gates.spec_review_mode）</span>
              </>
            }
            rules={[{ required: true, message: '请选择 SPEC 方案评审模式' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="auto">
                  <strong>auto</strong> — 默认全量评审
                  <div>
                    <Text type="secondary">
                      草稿晋升时默认全部进入方案评审；仅当 fast-track、能力目录 ≤ 1、
                      交付物声明 ≤ 3 且非 evo- 前缀时才跳过评审直通 ready。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="never">
                  <strong>never</strong> — 完全关闭
                  <div>
                    <Text type="secondary">
                      跳过方案评审门禁，drafted 晋升直接进入 ready 并调度（整体逃生门）。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            name="approve_mode"
            label={
              <>
                推送审批模式<span className="label-note">（gates.approve_mode）</span>
              </>
            }
            rules={[{ required: true, message: '请选择推送审批模式' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="manual">
                  <strong>manual</strong> — 人工审批
                  <div>
                    <Text type="secondary">
                      SPEC 完成后停留在 done，等待 /fenix-approve 人工推送。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="auto">
                  <strong>auto</strong> — 自动推送
                  <div>
                    <Text type="secondary">
                      SPEC 完成后 daemon 自动执行 git push origin fenix/&lt;spec&gt;。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
        </Form>
      </Card>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="approval" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave}>
          保存
        </Button>
      </div>
    </div>
  );
}
