import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckOutlined,
  FormOutlined,
} from "@ant-design/icons";
import { Button, Divider, Modal, Space, Steps, Typography } from "antd";
import { useEffect, useState } from "react";
import { GUIDE_STEPS } from "./userGuideSteps";

interface UserGuideModalProps {
  open: boolean;
  onClose: () => void;
  onNavigate: (path: string) => void;
}

export default function UserGuideModal({ open, onClose, onNavigate }: UserGuideModalProps) {
  const [current, setCurrent] = useState(0);
  const step = GUIDE_STEPS[current];
  const StepIcon = step.icon;
  const isLast = current === GUIDE_STEPS.length - 1;

  useEffect(() => {
    if (open) setCurrent(0);
  }, [open]);

  const goToStepPage = () => {
    onClose();
    onNavigate(step.path);
  };

  return (
    <Modal
      className="user-guide-modal"
      open={open}
      title={
        <Space size={10}>
          <img className="user-guide-brand-image" src="/resumeforge-icon.png" alt="" />
          <span>欢迎使用简历通</span>
        </Space>
      }
      width={720}
      onCancel={onClose}
      footer={
        <div className="user-guide-footer">
          <Button onClick={onClose}>稍后查看</Button>
          <Space wrap>
            <Button
              disabled={current === 0}
              icon={<ArrowLeftOutlined />}
              onClick={() => setCurrent(current - 1)}
            >
              上一步
            </Button>
            <Button type="link" icon={<FormOutlined />} onClick={goToStepPage}>
              {step.actionLabel}
            </Button>
            {isLast ? (
              <Button type="primary" icon={<CheckOutlined />} onClick={onClose}>
                开始使用
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<ArrowRightOutlined />}
                onClick={() => setCurrent(current + 1)}
              >
                下一步
              </Button>
            )}
          </Space>
        </div>
      }
    >
      {/* 步骤竖排在左侧当导航，内容在右侧。
          横排一行的做法在模块变多之后标题会互相挤压（截图反馈"小标题有点拥挤"）：
          9 个步骤平分 720px，每个标题只剩 70 多像素，中文标题被迫折成两三行。
          竖排后每个标题独占一行，再加模块也不用重新排版。 */}
      <div className="user-guide-body">
        <Steps
          className="user-guide-steps"
          direction="vertical"
          size="small"
          current={current}
          items={GUIDE_STEPS.map(({ title }) => ({ title }))}
          onChange={setCurrent}
        />
        <Divider type="vertical" className="user-guide-divider" />
        <section className="user-guide-step-content" aria-live="polite">
          <div className="user-guide-step-icon" aria-hidden="true">
            <StepIcon />
          </div>
          <div className="user-guide-step-copy">
            <Typography.Title level={4}>{step.heading}</Typography.Title>
            <Typography.Paragraph className="user-guide-description">
              {step.description}
            </Typography.Paragraph>
            <ul className="user-guide-points">
              {step.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </Modal>
  );
}
