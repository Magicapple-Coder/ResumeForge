/**
 * 「官网采集还在打磨中」说明弹窗。
 *
 * 存在的理由只有一个：**防止误会**。采集读不出某个站点时，用户很容易理解成
 * "我填错了"或者"这家公司没在招人"；这两件事都会让他做出错误决定（改地址改半天、
 * 或者干脆以为数据是假的）。所以这里把能力边界、结论怎么读、后续怎么办一次说清。
 *
 * 文案只承诺两件能兑现的事：**能读什么**（公开岗位）与**读不出时会说什么**
 * （报告里给依据，写"无法确认"而不是假装抓全了）。不写"很快支持所有网站"这类
 * 没依据的承诺——功能还没做到那一步。
 */
import { Alert, Button, Modal, Space, Typography } from "antd";

const { Paragraph, Text } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function OfficialBetaNoticeModal({ open, onClose }: Props) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="官网采集还在打磨中，先看这几点"
      width="min(620px, 94vw)"
      footer={
        <Button type="primary" onClick={onClose}>
          我知道了
        </Button>
      }
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          message="这个模块还不完善，会在后续版本逐步修复与扩充"
          description={
            <>
              它现在能读一部分公司的公开招聘岗位，但<Text strong>不保证每个站点都能抓全</Text>。
              遇到读不出来的情况，多半不是你的操作问题。
            </>
          }
        />
        <Paragraph style={{ marginBottom: 0 }}>
          <Text strong>它现在能做什么：</Text>
          填入公司官网或招聘页地址，识别背后的招聘系统，读取公开岗位并给出一句
          「这次抓全了没有」的结论——已确认为全量 / 已确认不全 / 无法确认，附可展开的依据。
        </Paragraph>
        <Paragraph style={{ marginBottom: 0 }}>
          <Text strong>哪里可能不行：</Text>
          需要登录、有验证码、站点反爬、页面结构特殊或改版、复杂脚本渲染与特殊翻页，
          都可能让它读不出或读不全；职位描述等字段也可能不完整。
        </Paragraph>
        <Paragraph style={{ marginBottom: 0 }}>
          <Text strong>结论怎么读：</Text>
          <Text mark>「无法确认」不等于「这家公司没有岗位」</Text>
          ——它只表示这一次没能拿到可靠的凭据。重要岗位请到官网核对一次。
        </Paragraph>
        <Paragraph style={{ marginBottom: 0 }}>
          <Text strong>我们会怎么处理：</Text>
          读不出的站点会在后续版本逐步修复与补充适配；每次采集的逐层依据都留在
          「采集记录」里，便于你判断这次结果能不能用，也便于我们定位问题。
        </Paragraph>
      </Space>
    </Modal>
  );
}
