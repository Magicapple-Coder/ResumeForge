/**
 * 「生成完成」的提示音。
 *
 * 为什么用 Web Audio 现场合成而不是塞一个 mp3：
 * - **不引入二进制资源**：仓库里不放音频文件，也就没有"某个平台播放不了"的编解码差异；
 * - **体积为零**：两声短音，几行代码；
 * - **可控**：时长、音量、音高都在这里，用户关掉开关就彻底不响。
 *
 * 浏览器的自动播放策略要求音频必须由**用户手势**触发过才允许播放。这些提示音都发生在
 * "用户点过按钮之后"（生成简历、跑批次），所以在同一页面会话里是允许的；万一被拦下，
 * 这里静默失败——**没有声音是可以接受的，抛异常打断正常流程不行**。
 */

const STORAGE_KEY = "resumeforge.notify-sound";
/** 两声短音：先上行再回落，比单音更像"完成"而不是"报错"。 */
const NOTES: { frequency: number; start: number; duration: number }[] = [
  { frequency: 880, start: 0, duration: 0.12 },
  { frequency: 1174.7, start: 0.14, duration: 0.16 },
];

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function getStorage(): StorageLike | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

/** 用户是否开了提示音（默认开：用户明确要求"完成后要有提醒声"）。 */
export function isSoundEnabled(storage: StorageLike | undefined = getStorage()): boolean {
  if (!storage) return true;
  try {
    return storage.getItem(STORAGE_KEY) !== "0";
  } catch {
    return true;
  }
}

export function setSoundEnabled(
  enabled: boolean,
  storage: StorageLike | undefined = getStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    // 存储不可用不影响其它功能，只是这次设置保存不下来。
  }
}

/** 播放"完成"提示音；被浏览器拦下或环境不支持时静默返回。 */
export function playDoneSound(): void {
  if (!isSoundEnabled()) return;
  if (typeof window === "undefined") return;
  const AudioContextCtor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextCtor) return;
  try {
    const context = new AudioContextCtor();
    const start = context.currentTime;
    for (const note of NOTES) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = note.frequency;
      // 淡入淡出：直接开关会有"咔哒"声。
      gain.gain.setValueAtTime(0, start + note.start);
      gain.gain.linearRampToValueAtTime(0.18, start + note.start + 0.02);
      gain.gain.linearRampToValueAtTime(0, start + note.start + note.duration);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(start + note.start);
      oscillator.stop(start + note.start + note.duration + 0.02);
    }
    // 用完就关，避免长期占着音频通道（一个页面里会响很多次）。
    window.setTimeout(() => void context.close().catch(() => undefined), 600);
  } catch {
    // 声音失败不是错误路径，不该影响调用方。
  }
}

export { STORAGE_KEY as NOTIFY_SOUND_STORAGE_KEY };
