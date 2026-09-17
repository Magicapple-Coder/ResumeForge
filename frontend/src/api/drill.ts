/** 面试深挖接口：开场、逐轮回答、提前收尾、复盘与复练。 */
import type {
  DrillAnswerResult,
  DrillCreatePayload,
  DrillRehearseResult,
  DrillRehearsalRow,
  DrillSession,
  DrillSessionBrief,
} from "../types";
import { buildQuery, request } from "./client";

export function listDrillSessions(params: { status?: string } = {}): Promise<DrillSessionBrief[]> {
  return request(`/drill${buildQuery(params)}`);
}

/** 开一场深挖。第一题的**评分契约**会在这一步就落库——用户看到问题时标准已经定下来。 */
export function createDrillSession(payload: DrillCreatePayload): Promise<DrillSession> {
  return request("/drill", { method: "POST", body: JSON.stringify(payload) });
}

export function getDrillSession(id: number): Promise<DrillSession> {
  return request(`/drill/${id}`);
}

/** 回答当前这一问。状态由后端按契约判定，前端不传。 */
export function answerDrill(id: number, answer: string): Promise<DrillAnswerResult> {
  return request(`/drill/${id}/answer`, {
    method: "POST",
    body: JSON.stringify({ answer }),
  });
}

/** 提前结束并出复盘。 */
export function finishDrill(id: number): Promise<DrillSession> {
  return request(`/drill/${id}/finish`, { method: "POST" });
}

export function deleteDrillSession(id: number): Promise<void> {
  return request(`/drill/${id}`, { method: "DELETE" });
}

/** 复练队列：只含"部分验证 / 未验证 / 存在矛盾"的主张。 */
export function listRehearsal(id: number): Promise<DrillRehearsalRow[]> {
  return request(`/drill/${id}/rehearsal`);
}

/** 把复练队列里的一条变成一个可回答的新问题（不落库）。 */
export function rehearse(id: number, payload: DrillRehearsalRow): Promise<DrillRehearseResult> {
  return request(`/drill/${id}/rehearse`, {
    method: "POST",
    body: JSON.stringify({
      claim_title: payload.claim_title,
      kind: payload.kind,
      why: payload.why,
    }),
  });
}
