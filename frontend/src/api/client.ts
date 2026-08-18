/** 统一请求封装：JSON 解析、错误信息提取、友好报错。 */

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** 把 query 对象转成查询串，跳过空值 */
export function buildQuery(params: object): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

/** 从响应体中提取错误信息（FastAPI 的 detail 可能是字符串或校验错误数组） */
export async function extractError(resp: Response): Promise<string> {
  try {
    const data = await resp.json();
    const detail = data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      return detail.map((item) => item?.msg ?? String(item)).join("；");
    }
  } catch {
    // 响应体不是 JSON 时退回状态码提示
  }
  return `请求失败（HTTP ${resp.status}）`;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const resp = await fetch(`/api${path}`, {
    ...options,
    headers,
  });
  if (!resp.ok) {
    throw new ApiError(await extractError(resp), resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
