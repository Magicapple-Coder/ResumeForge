import {
  FileTextOutlined,
  HomeOutlined,
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
    title: "配置模型",
    heading: "先决定是否使用 AI",
    description:
      "手写简历不需要模型配置；需要 AI 生成或岗位建议时，再到设置中填写你自己的兼容接口。",
    points: [
      "选择预设或填写 Base URL、模型名和 API Key。",
      "点击“测试连接”确认配置可用。",
      "密钥只保存在本机数据库，页面只显示脱敏占位符。",
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
      "先填写基本信息和教育经历，再补充项目与技能。",
      "每段经历可以附加 Markdown/TXT 总结文件作为参考。",
      "资料保存后仍可随时编辑、排序和补充。",
    ],
    path: "/profile",
    actionLabel: "前往我的资料",
    icon: ProfileOutlined,
  },
  {
    title: "添加岗位",
    heading: "从目标岗位开始准备",
    description: "岗位广场支持手动填写，也支持粘贴官网招聘信息后识别字段；识别结果入库前仍可核对。",
    points: [
      "保存职位名称、公司、地点、描述和任职要求。",
      "用备注、收藏和状态管理投递进度。",
      "一个岗位可以关联多份不同版本的简历。",
    ],
    path: "/jobs",
    actionLabel: "前往岗位广场",
    icon: HomeOutlined,
  },
  {
    title: "生成与导出",
    heading: "选择 AI 生成或自行编写",
    description: "从岗位进入简历流程，预览后可以微调内容，再保存历史记录并导出。",
    points: [
      "AI 生成会按岗位筛选资料；自行编写会从资料预填。",
      "预览支持编辑、岗位化建议和关联岗位回看。",
      "HTML 用于 A4 打印，JSON 和 Markdown 适合保存与继续编辑。",
    ],
    path: "/resumes",
    actionLabel: "查看简历中心",
    icon: FileTextOutlined,
  },
];
