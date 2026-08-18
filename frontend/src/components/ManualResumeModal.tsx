/** 用户手写简历弹窗：用个人资料预填结构化表单，再保存为手写简历记录。 */
import { App, Modal, Spin } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { createManualResume } from "../api/resumes";
import { getProfile } from "../api/profile";
import type { Job, Profile, ResumeContent } from "../types";
import { profileToResumeContent } from "../utils/profileToResume";
import ResumeEditorModal from "./ResumeEditorModal";

interface Props {
  job: Job | null;
  onClose: () => void;
}

export default function ManualResumeModal({ job, onClose }: Props) {
  const { message } = App.useApp();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(false);
  const requestVersion = useRef(0);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const currentRequest = ++requestVersion.current;
    if (!job) {
      setProfile(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    void getProfile()
      .then((loadedProfile) => {
        if (currentRequest === requestVersion.current) setProfile(loadedProfile);
      })
      .catch((error) => {
        if (currentRequest !== requestVersion.current) return;
        message.error(error instanceof Error ? error.message : "读取个人资料失败");
        setProfile(null);
        onCloseRef.current();
      })
      .finally(() => {
        if (currentRequest === requestVersion.current) setLoading(false);
      });
    return () => {
      if (currentRequest === requestVersion.current) requestVersion.current += 1;
    };
  }, [job, message]);

  const content = useMemo(
    () => (profile ? profileToResumeContent(profile, job) : null),
    [job, profile],
  );

  const save = async (nextContent: ResumeContent) => {
    await createManualResume({ job_id: job?.id ?? null, content: nextContent });
    message.success("手写简历已保存到简历中心");
  };

  return (
    <>
      <Modal open={!!job && loading} footer={null} closable={false} maskClosable={false} centered>
        <div style={{ textAlign: "center", padding: "28px 0" }}>
          <Spin />
          <div style={{ marginTop: 12 }}>正在读取我的资料…</div>
        </div>
      </Modal>
      <ResumeEditorModal
        open={!!job && !loading && !!content}
        content={content}
        title={job ? `自行编写「${job.title}」简历` : "自行编写简历"}
        description="已从我的资料预填基本信息和经历，你可以直接修改、删减或补充后保存。"
        saveLabel="保存手写简历"
        onClose={onClose}
        onSave={save}
      />
    </>
  );
}
