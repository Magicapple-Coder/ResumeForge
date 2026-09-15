/** 个人资料及其粘贴识别结果。 */

export interface Education {
  id?: number;
  school: string;
  major: string;
  degree: string;
  start_date: string;
  end_date: string;
  gpa: string;
  courses: string;
  achievements: string;
  reference_file_name: string;
  reference_content: string;
}

export interface Experience {
  id?: number;
  company: string;
  role: string;
  start_date: string;
  end_date: string;
  description: string;
  reference_file_name: string;
  reference_content: string;
}

export interface CampusExperience {
  id?: number;
  organization: string;
  role: string;
  start_date: string;
  end_date: string;
  description: string;
  reference_file_name: string;
  reference_content: string;
}

export interface Project {
  id?: number;
  name: string;
  role: string;
  start_date: string;
  end_date: string;
  tech_stack: string;
  description: string;
  highlights: string;
  reference_file_name: string;
  reference_content: string;
}

export interface Skill {
  id?: number;
  name: string;
  level: string;
}

export interface Award {
  id?: number;
  name: string;
  date: string;
  description: string;
}

export interface Profile {
  id: number;
  photo: string;
  name: string;
  gender: string;
  birth_year: string;
  phone: string;
  email: string;
  city: string;
  target_city: string;
  job_intent: string;
  personal_website: string;
  github: string;
  summary: string;
  section_order: string[];
  educations: Education[];
  experiences: Experience[];
  campus_experiences: CampusExperience[];
  projects: Project[];
  skills: Skill[];
  awards: Award[];
  updated_at?: string;
}

export type ProfileTextParseResult = Omit<Profile, "id" | "updated_at"> & {
  warnings: string[];
  recognition_source: "ai" | "local";
  /** 图片识别时模型逐字抄录的原文；纯文本识别为空。 */
  recognized_text: string;
};
