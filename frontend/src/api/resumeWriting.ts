/** 简历写作增强接口：STAR / 话术 / 润色 / 翻译 / 版本对比。 */
import type {
  PhraseMode,
  PhrasesResult,
  PolishResult,
  PolishStyle,
  ResumeDiff,
  StarRewriteResult,
  TranslateDirection,
  TranslateResult,
} from "../types/resumeWriting";
import { request } from "./client";

export function rewriteStar(
  id: number,
  text: string,
  claimId?: number,
): Promise<StarRewriteResult> {
  return request(`/resumes/${id}/writing/star`, {
    method: "POST",
    body: JSON.stringify({ text, claim_id: claimId }),
  });
}

export function generatePhrases(
  id: number,
  text: string,
  modes: PhraseMode[],
): Promise<PhrasesResult> {
  return request(`/resumes/${id}/writing/phrases`, {
    method: "POST",
    body: JSON.stringify({ text, modes }),
  });
}

export function polishResumeText(
  id: number,
  text: string,
  style: PolishStyle,
): Promise<PolishResult> {
  return request(`/resumes/${id}/writing/polish`, {
    method: "POST",
    body: JSON.stringify({ text, style }),
  });
}

export function translateResumeText(
  id: number,
  text: string,
  direction: TranslateDirection,
): Promise<TranslateResult> {
  return request(`/resumes/${id}/writing/translate`, {
    method: "POST",
    body: JSON.stringify({ text, direction }),
  });
}

export function diffResume(id: number, againstId: number): Promise<ResumeDiff> {
  return request(`/resumes/${id}/diff`, {
    method: "POST",
    body: JSON.stringify({ against_id: againstId }),
  });
}

/** 按「用户点中的那一栏」定向重写；返回的是**建议**，服务端不改简历。 */
export function rewriteResumeField(
  id: number,
  path: string,
  instruction: string,
): Promise<{
  path: string;
  label: string;
  context: string;
  original: string;
  result: string;
  /** `lines` = 整段（若干部要点），`text` = 单段。 */
  kind?: "text" | "lines";
  lines?: string[];
}> {
  return request(`/resumes/${id}/writing/rewrite-field`, {
    method: "POST",
    body: JSON.stringify({ path, instruction }),
  });
}
