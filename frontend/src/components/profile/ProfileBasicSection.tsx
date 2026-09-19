/** 个人资料基本信息与简历照片（多张可切换）。 */

import { Card, Col, Form, Input, Row } from "antd";
import ProfilePhotoPanel from "./ProfilePhotoPanel";

interface Props {
  photo: string;
  editing: boolean;
  saving: boolean;
  /** 切换照片时同步到资料表单（照片本身在照片库里已经落库）。 */
  onPhotoSelect: (dataUrl: string) => void;
}

export default function ProfileBasicSection({ photo, editing, saving, onPhotoSelect }: Props) {
  return (
    <Row gutter={[16, 16]} align="stretch" style={{ marginBottom: 16 }}>
      <Col xs={{ span: 24, order: 2 }} xl={{ span: 18, order: 1 }}>
        <Card size="small" className="profile-top-card">
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
          <ProfilePhotoPanel
            activePhoto={photo}
            disabled={!editing || saving}
            onSelect={onPhotoSelect}
          />
        </Card>
      </Col>
    </Row>
  );
}
