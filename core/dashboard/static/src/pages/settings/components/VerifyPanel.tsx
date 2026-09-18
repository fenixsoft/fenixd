import { Alert, Button, Card, Form, Radio, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton, { SETTINGS_ACTIONS_ROW_STYLE } from './SyncFromUserButton';

const { Text } = Typography;

interface VerifyPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function VerifyPanel({ config, onSave, project, onConfigSynced }: VerifyPanelProps) {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      static_scope: config.verify?.static_scope || 'main',
      deps_mode: config.verify?.deps_mode || 'prefer-offline',
    });
  }, [config.verify, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        verify: {
          static_scope: values.static_scope,
          deps_mode: values.deps_mode,
        },
      });
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>验证契约</h3>
      <Text type="secondary">
        静态验证契约（.fenix/verify.yaml）的被测实例服务范围。两种范围都会在
        每轮验证前执行契约的 prepare 构建步骤，并把验证场景 URL 全量改写到本次启动的实例。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} layout="vertical">
          <Form.Item
            name="static_scope"
            label={
              <>
                验证实例范围<span className="label-note">（verify.static_scope）</span>
              </>
            }
            rules={[{ required: true, message: '请选择服务范围' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="main">
                  <strong>main</strong> — 在 main 起服务进行验证
                  <div>
                    <Text type="secondary">
                      在主树构建并启动被测实例。实现合并进主树后产物必然新鲜，
                      与现有运行实例共享，资源占用最小。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="worktree">
                  <strong>worktree</strong> — 在 worktree 起服务进行验证
                  <div>
                    <Text type="secondary">
                      在专用 serving worktree 内构建并启动服务，与主树运行实例
                      完全隔离（验证流量不影响主实例）。每次 HEAD 变化自动重建
                      worktree 与产物。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            name="deps_mode"
            label={
              <>
                依赖供给模式<span className="label-note">（verify.deps_mode）</span>
              </>
            }
            rules={[{ required: true, message: '请选择依赖供给模式' }]}
            extra="设置 worktree 中 node_modules 的引用方式，仅使用 node.js 的项目需要设置此选项"
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="prefer-offline">
                  <strong>prefer-offline</strong> — npm 缓存安装（默认）
                  <div>
                    <Text type="secondary">
                      在 worktree 内 npm ci --prefer-offline（锁文件严格安装、
                      走用户级 npm 缓存），失败回退 npm install。无共享 inode，
                      最安全；首次安装约数十秒。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="hardlink">
                  <strong>hardlink</strong> — 主树硬链接副本
                  <div>
                    <Text type="secondary">
                      秒级完成、共享 inode 不占双倍空间。npm 更新包 = 重新解包
                      （新 inode），主树不受影响；但构建缓存等 in-place 写入会
                      穿透共享 inode——避免主树与 worktree 并发构建。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
        </Form>
      </Card>
      <Card title="构建产物路径" style={{ marginTop: 12 }}>
        <Typography.Paragraph type="secondary">
          worktree.build_artifact_paths —— 声明项目的构建产物路径（只读展示，
          由 .fenix/config.yaml 手工编写），供 merge-back WIP 重叠检查把产物与
          语义内容区分处理（产物对齐 HEAD、不进入 stash，避免 pop 冲突与误报
          告警）。支持目录前缀（如 dist/，须以 / 结尾）与文件通配（如
          release-*.zip，含 *）；未配置（空）时回退框架默认仅在
          core/dashboard/static 内判定。
        </Typography.Paragraph>
        {config.worktree?.build_artifact_paths?.length ? (
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {config.worktree.build_artifact_paths.map((p, i) => (
              <li key={i}>
                <code>{p}</code>
              </li>
            ))}
          </ul>
        ) : (
          <Text type="secondary">未配置（使用框架默认判定集合）</Text>
        )}
      </Card>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="verify" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave}>
          保存
        </Button>
      </div>
    </div>
  );
}
