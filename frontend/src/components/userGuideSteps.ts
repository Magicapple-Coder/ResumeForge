import {
  DatabaseOutlined,
  FileTextOutlined,
  HomeOutlined,
  MessageOutlined,
  ProfileOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import type { ComponentType } from "react";

export interface GuideStep {
  title: string;
  heading: string;
  description: string;
  points: string[];
  path: string;
  actionLabel: string;
  icon: ComponentType;
}

/**
 * 使用指南的步骤。
 *
 * 这是应用内的说明书，也是新用户唯一会主动打开的那份——`docs/user-guide.md` 更全，但没人会在
 * 装好应用之前去读它。因此**用户可见的新功能要么写进这里，要么在 `docs/user-guide.md` 里说明
 * 为什么不必写**；判据是"用户会不会因为不知道而用错或用不上"。
 */
export const GUIDE_STEPS: GuideStep[] = [
  {
    title: "配置 AI",
    heading: "选择预设或自定义模型",
    description:
      "手动管理岗位、资料和自行编写简历无需模型；AI 生成、岗位需求解读、优化建议、截图识别和求职助手需要兼容 OpenAI Chat Completions 的模型接口。",
    points: [
      "可选择内置预设；「自定义模型（OpenAI 兼容）」保留已填内容，「纯手动配置」则清空 Base URL 与模型名称，适合中转站或公司网关。",
      "先点击“测试连接”，确认成功后保存；常用配置可命名保存并一键切换。",
      "推理型模型如果回答被思考过程挤空，可在「最大输出 Token」里选「不限制」。",
      "API Key 保存在本机数据库；模型请求仍会发送到你选择的服务商。",
    ],
    path: "/settings",
    actionLabel: "前往设置",
    icon: SettingOutlined,
  },
  {
    title: "完善资料",
    heading: "建立你的事实资料库",
    description: "把教育、经历、项目、校园活动和技能集中维护，生成不同岗位的简历时可以按岗位筛选。",
    points: [
      "可手动填写，也可粘贴整段个人资料；还能按 Ctrl+V 贴资料截图，或上传 pdf/docx 简历文档（文字在本机提取）识别成可编辑草稿。",
      "每段经历可以附加 Markdown/TXT 总结文件，补充项目细节与成果。",
      "方向还没定的时候用「通用简历」：不绑定岗位，AI 生成或从头手写都行。",
      "资料保存后仍可编辑和排序；简历照片留在本机，不会发送给模型。",
    ],
    path: "/profile",
    actionLabel: "前往我的资料",
    icon: ProfileOutlined,
  },
  {
    title: "导入岗位",
    heading: "手动填写或粘贴招聘信息",
    description: "可逐项手动填写，也可粘贴完整招聘信息，让系统识别并分类回填。",
    points: [
      "系统会拆分职位、公司、地点、职责、要求、其他信息、发布时间和投递链接。",
      "粘贴文字、贴截图或上传 pdf/docx 招聘文档都能识别（一次最多 4 个）；结果下方会常驻标明是 AI 识别还是本地规则，AI 不可用时会自动回退并说明原因。",
      "识别结果不会自动保存，请核对字段后再点击保存。",
    ],
    path: "/jobs",
    actionLabel: "前往岗位广场",
    icon: HomeOutlined,
  },
  {
    title: "制作简历",
    heading: "按岗位生成，或写一份通用的",
    description: "从岗位进入简历流程，预览后可以微调内容，再保存历史记录并导出。",
    points: [
      "AI 生成会按岗位筛选资料并可选择美化程度；自行编写会从资料预填并显示岗位参考。",
      "通用简历不做岗位筛选：各方向的经历、项目、技能和奖项都保留，只受篇幅预算限制。",
      "预览支持点击定位编辑、岗位化建议、缩放和抓手浏览。",
      "保存后可回看关联岗位；HTML 用于 A4 打印，JSON 和 Markdown 适合存档。",
    ],
    path: "/resumes",
    actionLabel: "查看简历中心",
    icon: FileTextOutlined,
  },
  {
    title: "求职助手",
    heading: "让助手直接帮你处理数据",
    description: "带着项目里的资料向助手提问，也可以在它明确告知后让它直接改动数据。",
    points: [
      "助手可以直接查询和修改项目里的岗位、简历与个人资料——但它不会替你删除任何数据。",
      "每次改动都会在回复里列出来并给出跳转入口，你可以在页面上核对。",
      "只在你主动选择时才会读取岗位、简历或脱敏资料；也支持附件和可选联网搜索。",
      "设置里的「助手技能」用一份提示词固定它的作答方式，例如固定的面试官追问风格。",
    ],
    path: "/assistant",
    actionLabel: "打开求职助手",
    icon: MessageOutlined,
  },
  {
    title: "数据备份",
    heading: "把数据带走，或换一份",
    description: "岗位、资料、简历、收藏和助手会话都在这台电脑上；换机器前先导出一份。",
    points: [
      "设置里的「数据集」可以把全部本地数据导出成一个压缩包，新电脑上导入即可完整还原。",
      "导入默认新建一份数据集，不碰当前正在用的那份；也可以在本机保留多份并随时切换。",
      "备份里不含大模型 API Key，恢复后需要重新填写并测试连接。",
    ],
    path: "/settings",
    actionLabel: "前往设置",
    icon: DatabaseOutlined,
  },
];
