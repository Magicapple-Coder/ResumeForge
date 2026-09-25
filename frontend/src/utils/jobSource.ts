/**
 * 岗位「来源」的两条规则，集中在一处。
 *
 * 为什么单独成模块：同一个概念在**两个地方**被判断——列表里的角标（这条岗位是采集来的
 * 还是手动加的）、以及从备选岗位导入时该写哪个来源值。两处各写一份的直接后果是它们会不一致，
 * 而这里已经踩过一次：导入时把来源写死成「备选岗位导入」，于是**从官网采集 / 投递台采集回来的
 * 岗位在岗位广场里全挂着「手动」角标**，用户看到的与自己做的事完全对不上。
 */
import type { Job, JobRecognitionSource } from "../types";

/**
 * 会被视为"自动采集"的来源值。
 *
 * 与后端 `schemas/job.py` 的 `RECOGNITION_SOURCE_AUTO`（`岗位采集` / `官网采集`）一致：
 * 旧版本的官网采集曾把 `官网采集` 写进来源列，新的候选导入统一写 `岗位采集`，
 * 读取侧不能只认其中一个。
 */
const COLLECTED_SOURCES = new Set<JobRecognitionSource>(["岗位采集", "官网采集"]);

/** 这条岗位算"采集来的"还是"手动加的"（列表职位列的角标口径）。 */
export function jobSourceKind(job: Pick<Job, "recognition_source">): "collected" | "manual" {
  return COLLECTED_SOURCES.has(job.recognition_source) ? "collected" : "manual";
}

/**
 * 从备选岗位导入到岗位广场时，这条岗位该写哪个来源。
 *
 * **必须继承候选自己的来路**，不能一律写「备选岗位导入」：
 * - 有 `collect_task_id` ⇒ 采集任务带回来的（投递台采集、官网采集都会写它）→「岗位采集」；
 * - 来源就是「官网采集」⇒ 官网采集导入的候选 →「官网采集」（保留更具体的那一个）；
 * - 其余（用户自己粘贴的）→「备选岗位导入」。
 */
/** 备选岗位里与来源判定有关的两个字段（候选的其它字段这里不关心）。 */
export interface CandidateOrigin {
  source: string;
  collect_task_id: number | null;
}

export function candidateImportSource(candidate: CandidateOrigin): JobRecognitionSource {
  if (candidate.collect_task_id !== null && candidate.collect_task_id !== undefined) {
    return "岗位采集";
  }
  if (candidate.source === "官网采集") return "官网采集";
  return "备选岗位导入";
}
