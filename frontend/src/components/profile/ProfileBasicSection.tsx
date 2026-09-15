/** 个人资料基本信息与简历照片表单。 */

import { CameraOutlined, DeleteOutlined, UserOutlined } from "@ant-design/icons";
import { Button, Card, Col, Form, Image, Input, Row, Space, Typography, Upload } from "antd";
import type { UploadProps } from "antd";

interface Props {
  photo: string;
  editing: boolean;
  saving: boolean;
  photoReading: boolean;
  beforePhotoUpload: UploadProps["beforeUpload"];
  onRemovePhoto: () => void;
}

export default function ProfileBasicSection({
  photo,
  editing,
  saving,
  photoReading,
  beforePhotoUpload,
  onRemovePhoto,
}: Props) {
  return (
    <Row gutter={[16, 16]} align="stretch" style={{ marginBottom: 16 }}>
      <Col xs={{ span: 24, order: 2 }} xl={{ span: 18, order: 1 }}>
        <Card size="small" title="基本信息" className="profile-top-card">
          <Row gutter={12}>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="name" label="姓名" rules={[{ required: true, message: "必填" }]}>
                <Input placeholder="你的姓名" />
              </Form.Item>
            </Col>
            <Col xs={12} sm={6} lg={8}>
              <Form.Item name="gender" label="性别">
                <Input placeholder="男 / 女" />
              </Form.Item>
            </Col>
            <Col xs={12} sm={6} lg={8}>
              <Form.Item name="birth_year" label="出生年份">
                <Input placeholder="2004" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="phone" label="手机号">
                <Input placeholder="13800000000" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item
                name="email"
                label="邮箱"
                rules={[{ type: "email", message: "邮箱格式不正确" }]}
              >
                <Input placeholder="you@example.com" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="city" label="所在城市">
                <Input placeholder="天津" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="target_city" label="意向城市">
                <Input placeholder="北京 / 深圳 / 杭州" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="job_intent" label="求职意向">
                <Input placeholder="如：后端开发工程师" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="github" label="GitHub 主页">
                <Input placeholder="https://github.com/xxx" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="personal_website" label="个人网站 / 博客">
                <Input placeholder="选填" />
              </Form.Item>
            </Col>
          </Row>
        </Card>
      </Col>

      <Col xs={{ span: 24, order: 1 }} xl={{ span: 6, order: 2 }}>
        <Card size="small" title="简历照片" className="profile-top-card">
          <div className="profile-photo-panel">
            <div className="profile-photo-frame">
              {photo ? (
                <Image src={photo} alt="简历照片" preview={false} />
              ) : (
                <UserOutlined className="profile-photo-placeholder" />
              )}
            </div>
            <Space wrap>
              <Upload
                accept="image/jpeg,image/png,image/webp"
                beforeUpload={beforePhotoUpload}
                showUploadList={false}
                maxCount={1}
                disabled={!editing || saving || photoReading}
              >
                <Button icon={<CameraOutlined />} loading={photoReading}>
                  {photo ? "更换照片" : "选择照片"}
                </Button>
              </Upload>
              {photo && (
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!editing || saving || photoReading}
                  onClick={onRemovePhoto}
                >
                  移除
                </Button>
              )}
            </Space>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              JPG、PNG 或 WebP，最大 2 MB
            </Typography.Text>
          </div>
        </Card>
      </Col>
    </Row>
  );
}
