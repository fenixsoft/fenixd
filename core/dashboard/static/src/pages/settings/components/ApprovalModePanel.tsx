import { Button, Card, Form, Radio, Typography } from 'antd';
import { useEffect, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton, { SETTINGS_ACTIONS_ROW_STYLE } from './SyncFromUserButton';

const { Text } = Typography;

// 单选选项行样式收敛（code-review item 5184fd263e11）：4 组 × 2 行共 8 个
// 选项行重复书写两组静态内联样式（组内首行带下间距、次行不带）——抽模块级
// 常量单源，避免逐处漂移。
const RADIO_OPTION_ROW_SPACED_STYLE: React.CSSProperties = {
  display: 'block',
  marginBottom: 16,
};
const RADIO_OPTION_ROW_STYLE: React.CSSProperties = { display: 'block' };

// gates 缺省值单源（code-review item 3f618ddb51cb）：四个缺省值旧实现
// 在 useEffect 与 <Form initialValues> 中各写一份，只改一处会漂移——抽
// DEFAULT_GATES 常量 + gatesFormValues 构建函数供两处复用。
const DEFAULT_GATES = {
  promote_mode: 'auto',
  approve_mode: 'manual',
  spec_review_mode: 'auto',
  start_after_scope: 'dispatch',
} as const;

function gatesFormValues(gates: ConfigData['gates']) {
  return {
    promote_mode: gates.promote_mode || DEFAULT_GATES.promote_mode,
    approve_mode: gates.approve_mode || DEFAULT_GATES.approve_mode,
    spec_review_mode: gates.spec_review_mode || DEFAULT_GATES.spec_review_mode,
    start_after_scope: gates.start_after_scope || DEFAULT_GATES.start_after_scope,
  };
}

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
  // 保存重入守卫（code-review item 589c1c98c5a4）：onSave 是异步，提交期间
  // 按钮可继续点击会发出重叠保存请求（并发写同一配置文件，结果取决于响应
  // 到达顺序）——saving 期间置 loading/disabled 并在入口短路。
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // 确保字段有值，使用配置值或默认值
    form.setFieldsValue(gatesFormValues(config.gates));
  }, [config.gates, form]);

  const handleSave = async () => {
    if (saving) {
      return;
    }
    setSaving(true);
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
          start_after_scope: values.start_after_scope,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h3>审批</h3>
      <Text type="secondary">
        草稿晋升（drafted → ready）与推送审批（done → push）行为。auto 推送模式将自动执行 git push 到远端，请谨慎使用。
        定时拾取（start_after）的覆盖范围：只约束实现派发，或同时按住晋升与评审。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form
          form={form}
          initialValues={gatesFormValues(config.gates)}
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
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              控制草稿 SPEC 如何进入调度。manual 停留在草稿态由人工确认放行（/fenix-ready、
              项目页按钮或 CLI）；auto 注册后立即自动晋升 ready 并进入调度，未经人工审阅。
              缺省 auto。
            </Text>
            <Radio.Group>
              <div style={RADIO_OPTION_ROW_SPACED_STYLE}>
                <Radio value="manual">
                  <strong>manual</strong> — 人工审批
                  <div>
                    <Text type="secondary">
                      SPEC 停留在草稿态供人工阅读，确认后经 /fenix-ready、项目页按钮或 CLI 手动放行。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={RADIO_OPTION_ROW_STYLE}>
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
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              控制 drafted → ready 之间是否过方案评审门禁。auto 默认全量评审，
              仅 fast-track、能力目录 ≤ 1、交付物声明 ≤ 3 且非 evo- 前缀时跳过；
              never 完全关闭门禁，作为逃生门跳过评审直接调度。缺省 auto。
            </Text>
            <Radio.Group>
              <div style={RADIO_OPTION_ROW_SPACED_STYLE}>
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
              <div style={RADIO_OPTION_ROW_STYLE}>
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
          {/* 定时拾取覆盖范围（add-start-after-scope-config，置于方案评审与推送审批之间） */}
          <Form.Item
            name="start_after_scope"
            label={
              <>
                定时拾取覆盖范围<span className="label-note">（gates.start_after_scope）</span>
              </>
            }
            rules={[{ required: true, message: '请选择定时拾取覆盖范围' }]}
          >
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              定时拾取（start_after）的覆盖范围。dispatch 只把实现派发挂起到点，
              晋升与方案评审照常走；full 同时按住晋升与评审，SPEC 停在草稿态，
              到期/激活才一并放行。缺省 dispatch。
            </Text>
            <Radio.Group>
              <div style={RADIO_OPTION_ROW_SPACED_STYLE}>
                <Radio value="dispatch">
                  <strong>dispatch</strong> — 只约束实现派发
                  <div>
                    <Text type="secondary">
                      定时/待激活 SPEC 立即晋升并跑方案评审，实现等到点（缺省）。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={RADIO_OPTION_ROW_STYLE}>
                <Radio value="full">
                  <strong>full</strong> — 同时按住晋升与评审
                  <div>
                    <Text type="secondary">
                      SPEC 停在草稿态，到期/激活才晋升并评审。
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
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              控制 done 态 SPEC 向远端推送的行为。manual 停留在 done 等待 /fenix-approve
              人工推送；auto 由 daemon 自动执行 git push 到远端，会对外发布代码，
              请谨慎使用。缺省 manual。
            </Text>
            <Radio.Group>
              <div style={RADIO_OPTION_ROW_SPACED_STYLE}>
                <Radio value="manual">
                  <strong>manual</strong> — 人工审批
                  <div>
                    <Text type="secondary">
                      SPEC 完成后停留在 done，等待 /fenix-approve 人工推送。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={RADIO_OPTION_ROW_STYLE}>
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
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving}>
          保存
        </Button>
      </div>
    </div>
  );
}
