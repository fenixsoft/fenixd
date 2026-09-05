import { Alert, Button, Card, Form, Input, Switch, TimePicker, Typography, message } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';
import { getTodo, saveTodo } from '@/services/dashboard';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;
const { TextArea } = Input;

// run_at 缺省与后端 ConfigLoader.SELF_REVIEW_DEFAULT_RUN_AT 一致（凌晨两点）
const DEFAULT_RUN_AT = '02:00';

interface SelfReviewPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 项目名；undefined = 用户级作用域（todo.md 为项目级文件，不显示编辑区） */
  project?: string;
}

export default function SelfReviewPanel({ config, onSave, project }: SelfReviewPanelProps) {
  const [form] = Form.useForm();

  const initial = {
    enabled: config.self_review?.enabled ?? false,
    // TimePicker 值为 dayjs 对象（结构性保证 HH:mm 合法），保存时转回字符串
    run_at: dayjs(config.self_review?.run_at ?? DEFAULT_RUN_AT, 'HH:mm'),
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
          run_at: values.run_at.format('HH:mm'),
          read_todo: values.read_todo,
        },
      });
    } catch {
      // 校验失败：antd 已在表单内渲染 explain-error 提示，无需额外日志
    }
  };

  // ── todo.md 查看与编辑（项目级作用域）──
  const [todoDraft, setTodoDraft] = useState<string>('');
  const [todoExists, setTodoExists] = useState<boolean>(false);
  const [todoLoading, setTodoLoading] = useState(false);
  const [todoSaving, setTodoSaving] = useState(false);

  useEffect(() => {
    if (!project) return;
    let cancelled = false;
    const load = async () => {
      setTodoLoading(true);
      try {
        const d = await getTodo(project);
        if (!cancelled) {
          setTodoDraft(d.content);
          setTodoExists(d.exists);
        }
      } catch (e) {
        console.error('Failed to load todo.md:', e);
        if (!cancelled) message.error(`加载 todo.md 失败：${e instanceof Error ? e.message : e}`);
      } finally {
        if (!cancelled) setTodoLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [project]);

  const handleTodoSave = async () => {
    if (!project) return;
    setTodoSaving(true);
    try {
      await saveTodo(project, todoDraft);
      message.success('todo.md 已保存');
      setTodoExists(true);
      const d = await getTodo(project);
      setTodoDraft(d.content);
      setTodoExists(d.exists);
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : String(e);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save todo.md:', e);
    } finally {
      setTodoSaving(false);
    }
  };

  return (
    <div>
      <h3>自省</h3>
      <Text type="secondary">
        Fenix Daemon 每晚在指定时间由 Administrator Agent 自动执行当日工作回顾（浪费 /
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
            rules={[{ required: true, message: '请选择执行时间' }]}
          >
            <TimePicker format="HH:mm" allowClear={false} style={{ width: 160 }} />
          </Form.Item>
          <Text type="secondary">缺省 02:00。实际触发时刻为 run_at 后的第一个巡检周期。</Text>

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

      {/* todo.md 为项目级文件：仅项目级作用域提供查看与编辑 */}
      {project ? (
        <Card style={{ marginTop: 16 }} data-testid="todo-section">
          <h3 style={{ marginTop: 0 }}>todo.md</h3>
          <Text type="secondary">
            项目 <code>.fenix/todo.md</code>——自省 Agent 每晚追加写入当日回顾。
            保存为整文件覆写，请注意与 daemon 夜间追加的时序（建议日间编辑）。
          </Text>
          {!todoExists && !todoLoading && (
            <Alert
              style={{ marginTop: 8 }}
              type="info"
              showIcon
              message="尚无 todo.md（自省首次运行后生成），可保存以下内容提前创建。"
              data-testid="todo-missing-alert"
            />
          )}
          <TextArea
            data-testid="todo-textarea"
            value={todoDraft}
            onChange={(e) => setTodoDraft(e.target.value)}
            disabled={todoLoading}
            placeholder={'## 2026-09-04\n\n### 可改进\n- 证据：……'}
            autoSize={{ minRows: 10, maxRows: 24 }}
            style={{ marginTop: 12, fontFamily: 'monospace' }}
          />
          <div style={{ marginTop: 12, textAlign: 'right' }}>
            <Button
              style={{ marginRight: 8 }}
              onClick={async () => {
                const d = await getTodo(project);
                setTodoDraft(d.content);
                setTodoExists(d.exists);
                message.info('已从磁盘重新加载');
              }}
              data-testid="todo-reload"
            >
              重新加载
            </Button>
            <Button
              type="primary"
              loading={todoSaving}
              onClick={handleTodoSave}
              data-testid="todo-save"
            >
              保存 todo.md
            </Button>
          </div>
        </Card>
      ) : (
        <Card style={{ marginTop: 16 }}>
          <Text type="secondary">
            todo.md 为项目级文件（<code>.fenix/todo.md</code>）。查看与编辑请切换到项目级作用域。
          </Text>
        </Card>
      )}
    </div>
  );
}
