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
    // 结构化 detail：投递台的 409 就是这种形状（`{message, unanalyzed, gaps, site_unsupported…}`）。
    // 不取 message 的话，所有走 `request()` 的调用方只能看到「请求失败（HTTP 409）」——
    // 用户拿到的是一句没信息量的话，而真正的原因（例如"来源不支持自动投递，请先移出队列"）
    // 就躺在响应体里。
    if (detail && typeof detail === "object" && typeof detail.message === "string") {
      return detail.message;
    }
  } catch {
    // 响应体不是 JSON 时退回状态码提示
  }
  return `请求失败（HTTP ${resp.status}）`;
}

/** 从 Content-Disposition 里解析文件名，兼容 RFC 5987 的 filename* 形式 */
export function getFilenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const plainMatch = /filename="?([^";]+)"?/i.exec(header);
  return plainMatch ? plainMatch[1] : null;
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
