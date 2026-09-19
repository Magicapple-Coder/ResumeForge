/** 质量检测弹窗：风险扫描（R-08~R-09）与 ATS 本地检测（R-10）同用一个 Tabs 面板。 */
import { Modal, Tabs } from "antd";
import AtsCheckPanel from "./AtsCheckPanel";
import ResumeRiskPanel from "./ResumeRiskPanel";

interface Props {
  open: boolean;
  resumeId: number | null;
  onClose: () => void;
}

export default function ResumeQualityModal({ open, resumeId, onClose }: Props) {
  return (
    <Modal
      title="质量检测"
      open={open}
      onCancel={onClose}
      width="min(880px, calc(100vw - 24px))"
      footer={null}
      destroyOnHidden
      styles={{ body: { maxHeight: "calc(100vh - 200px)", overflowY: "auto" } }}
    >
      {resumeId != null && (
        <Tabs
          items={[
            {
              key: "risk",
              label: "风险扫描",
              children: <ResumeRiskPanel resumeId={resumeId} />,
            },
            {
              key: "ats",
              label: "ATS 检测",
              children: <AtsCheckPanel resumeId={resumeId} />,
            },
          ]}
        />
      )}
    </Modal>
  );
}
