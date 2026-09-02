import { Button, Card, Input, Typography, message } from 'antd';
import { useState, useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';
import { regenerateProjectDescription } from '@/services/dashboard';

const { TextArea } = Input;
const { Text } = Typography;

interface ProjectProfilePanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  project?: string;
}

export default function ProjectProfilePanel({ config, onSave, project }: ProjectProfilePanelProps) {
  const [description, setDescription] = useState(config.description || '');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setDescription(config.description || '');
  }, [config.description]);

  const handleSave = async () => {
    try {
      await onSave({ description });
      message.success('保存成功');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`保存失败：${errorMessage}`);
      console.error('Failed to save description:', error);
    }
  };

  const handleRegenerate = async () => {
    if (!project) {
      message.error('项目名称缺失，无法重新生成');
      return;
    }

    setLoading(true);
    try {
      const result = await regenerateProjectDescription(project);
      if (result.ok) {
        setDescription(result.description);
        message.success('简介重新生成成功');
        // 刷新配置以确保一致性
        await onSave({ description: result.description });
      } else {
        message.error(result.error || '重新生成失败');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      message.error(`重新生成失败：${errorMessage}`);
      console.error('Failed to regenerate description:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h3>项目简介</h3>
      <Text type="secondary">
        项目简介将展示在概览页项目卡片和项目列表页，帮助快速了解项目用途。
      </Text>
      <Card style={{ marginTop: 12 }}>
        <TextArea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="暂无简介"
          autoSize={{ minRows: 4, maxRows: 8 }}
          style={{ marginBottom: 16 }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Button onClick={handleRegenerate} loading={loading}>
            AI 重新生成
          </Button>
          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </div>
      </Card>
    </div>
  );
}
