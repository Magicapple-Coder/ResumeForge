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
      {/* labelPlacement="vertical"：标题放到图标下面，每项独占一列的整宽。
          这不只是换个样式——antd 只在**非**垂直标签时才给步骤项写 `white-space: nowrap`，
          横排时中文标题因此永远不换行，窄一点就整块被裁掉（"完善资料…"）。用这个官方属性
          把 nowrap 从源头上拿掉，比在自己的 CSS 里跟它抢优先级可靠。 */}
      <Steps
        className="user-guide-steps"
        current={current}
        items={GUIDE_STEPS.map(({ title }) => ({ title }))}
        onChange={setCurrent}
        labelPlacement="vertical"
      />
      <Divider />
      <section className="user-guide-step-content" aria-live="polite">
        <div className="user-guide-step-icon" aria-hidden="true">
          <StepIcon />
        </div>
        <div className="user-guide-step-copy">
          <Typography.Title level={4}>{step.heading}</Typography.Title>
          <Typography.Paragraph>{step.description}</Typography.Paragraph>
          <ul className="user-guide-points">
            {step.points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </div>
      </section>
    </Modal>
  );
}
