/** 新会话的引导提示和常用问题。 */

import { Button, Empty, Typography } from "antd";
import { STARTER_PROMPTS, type StarterPrompt } from "../assistantTypes";

export default function AssistantEmptyState({
  onChoosePrompt,
}: {
  onChoosePrompt: (prompt: StarterPrompt) => void;
}) {
  return (
    <div className="assistant-empty-state">
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <div className="assistant-empty-state-copy">
            <Typography.Text strong>可以这样问</Typography.Text>
            <Typography.Text type="secondary">
              可先关联岗位或简历，再按需开启资料和联网搜索。
            </Typography.Text>
          </div>
        }
      >
        <div className="assistant-starter-prompts" aria-label="常用求职提问">
          {STARTER_PROMPTS.map((prompt) => (
            <Button
              key={prompt.label}
              size="small"
              className="assistant-starter-prompt"
              onClick={() => onChoosePrompt(prompt)}
            >
              {prompt.label}
            </Button>
          ))}
        </div>
      </Empty>
    </div>
  );
}
