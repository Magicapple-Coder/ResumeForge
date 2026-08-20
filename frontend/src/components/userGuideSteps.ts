import {
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

export const GUIDE_STEPS: GuideStep[] = [
  {
    title: "配置 AI",
    heading: "选择预设或自定义模型",
    description:
      "手动管理岗位、资料和自行编写简历无需模型；AI 生成、岗位需求解读、优化建议和求职助手需要兼容 OpenAI Chat Completions 的模型接口。",
    points: [
      "可选择内置预设，或选择“自定义模型（OpenAI 兼容）”填写 Base URL、模型名称及服务商要求的 API Key。",
      "先点击“测试连接”，确认成功后保存；常用配置可命名保存并一键切换。",
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
      "可手动填写，也可粘贴整段个人资料并识别为可编辑草稿。",
      "每段经历可以附加 Markdown/TXT 总结文件，补充项目细节与成果。",
      "资料保存后仍可编辑和排序；简历照片留在本机，不会发送给模型。",
    ],
    path: "/profile",
    actionLabel: "前往我的资料",
    icon: ProfileOutlined,
  },
  {
    title: "导入岗位",
    heading: "手动填写或粘贴招聘信息",
    description: "可逐项手动填写，也可粘贴完整招聘信息，让系统在本地识别并分类回填。",
    points: [
      "系统会拆分职位、公司、地点、职责、要求、其他信息、发布时间和投递链接。",
      "粘贴识别只在本地生成可编辑草稿，不会访问招聘网站或调用大模型。",
      "识别结果不会自动保存，请核对字段后再点击保存。",
    ],
    path: "/jobs",
    actionLabel: "前往岗位广场",
    icon: HomeOutlined,
  },
  {
    title: "制作简历",
    heading: "选择 AI 生成或自行编写",
    description: "从岗位进入简历流程，预览后可以微调内容，再保存历史记录并导出。",
    points: [
      "AI 生成会按岗位筛选资料并可选择美化程度；自行编写会从资料预填并显示岗位参考。",
      "预览支持点击定位编辑、岗位化建议、缩放和抓手浏览。",
      "保存后可回看关联岗位；HTML 用于 A4 打印，JSON 和 Markdown 适合存档。",
    ],
    path: "/resumes",
    actionLabel: "查看简历中心",
    icon: FileTextOutlined,
  },
  {
    title: "管理与咨询",
    heading: "串联岗位、简历和求职准备",
    description: "收藏重要内容、查看岗位需求解读，或带着项目中的资料向求职助手继续提问。",
    points: [
      "岗位和简历可以相互跳转，收藏夹集中展示关注的岗位与简历版本。",
      "岗位需求解读只总结当前招聘原文，不会读取个人资料。",
      "求职助手仅在你主动选择时读取岗位、简历或脱敏资料，也支持附件和可选联网搜索。",
    ],
    path: "/assistant",
    actionLabel: "打开求职助手",
    icon: MessageOutlined,
  },
];
