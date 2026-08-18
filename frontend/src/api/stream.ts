/** SSE 流式响应读取：用于简历生成等长任务，逐事件回调。 */

import { ApiError, extractError } from "./client";

export interface SSEParserState {
  buffer: string;
  dataLines: string[];
}

export interface SSEParseResult {
  state: SSEParserState;
  events: string[];
}

export function createSSEParserState(): SSEParserState {
  return { buffer: "", dataLines: [] };
}

/**
 * Incrementally parse SSE text without depending on chunk boundaries.
 * Keeping this function pure makes CRLF, EOF and fragmented input behavior testable.
 */
export function parseSSEChunk(
  previous: SSEParserState,
  chunk: string,
  endOfStream = false,
): SSEParseResult {
  const source = previous.buffer + chunk;
  const dataLines = [...previous.dataLines];
  const events: string[] = [];
  let lineStart = 0;
  let cursor = 0;

  const processLine = (line: string) => {
    if (line === "") {
      if (dataLines.length > 0) events.push(dataLines.join("\n"));
      dataLines.length = 0;
      return;
    }
    if (line.startsWith(":")) return;
    const colonIndex = line.indexOf(":");
    const field = colonIndex === -1 ? line : line.slice(0, colonIndex);
    if (field !== "data") return;
    let value = colonIndex === -1 ? "" : line.slice(colonIndex + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    dataLines.push(value);
  };

  while (cursor < source.length) {
    const character = source[cursor];
    if (character === "\n") {
      processLine(source.slice(lineStart, cursor));
      cursor += 1;
      lineStart = cursor;
      continue;
    }
    if (character === "\r") {
      if (cursor + 1 >= source.length && !endOfStream) break;
      processLine(source.slice(lineStart, cursor));
      cursor += source[cursor + 1] === "\n" ? 2 : 1;
      lineStart = cursor;
      continue;
    }
    cursor += 1;
  }

  let buffer = source.slice(lineStart);
  if (endOfStream) {
    if (buffer) processLine(buffer);
    buffer = "";
    if (dataLines.length > 0) {
      events.push(dataLines.join("\n"));
      dataLines.length = 0;
    }
  }

  return { state: { buffer, dataLines }, events };
}

function dispatchEvents<T>(events: string[], onEvent: (event: T) => void): void {
  for (const data of events) {
    let event: T;
    try {
      event = JSON.parse(data) as T;
    } catch {
      throw new ApiError("流式响应格式异常，请重试");
    }
    onEvent(event);
  }
}

export async function consumeSSE<T>(
  url: string,
  body: unknown,
  onEvent: (event: T) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    throw new ApiError(await extractError(resp), resp.status);
  }
  if (!resp.body) {
    throw new ApiError("浏览器不支持流式响应，请更换现代浏览器");
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let parserState = createSSEParserState();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    const parsed = parseSSEChunk(parserState, decoder.decode(value, { stream: true }));
    parserState = parsed.state;
    dispatchEvents(parsed.events, onEvent);
  }

  const final = parseSSEChunk(parserState, decoder.decode(), true);
  dispatchEvents(final.events, onEvent);
}
