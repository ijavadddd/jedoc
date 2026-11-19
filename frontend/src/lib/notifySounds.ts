/** Status chimes via short WAV data-URLs (reliable under browser autoplay rules). */

let armed = false;
let lastStatus = "";
let lastAt = 0;
let dingUrl: string | null = null;
let dongUrl: string | null = null;
let sharedCtx: AudioContext | null = null;

function ensureCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!sharedCtx || sharedCtx.state === "closed") sharedCtx = new Ctor();
  return sharedCtx;
}

/** Encode a short mono WAV as a data URL (no network/assets). */
function wavDataUrl(freqs: number[], durationSec: number, volume = 0.4): string {
  const sampleRate = 22050;
  const samples = Math.floor(sampleRate * durationSec);
  const data = new Int16Array(samples);
  for (let i = 0; i < samples; i += 1) {
    const t = i / sampleRate;
    const env = Math.min(1, t * 40) * Math.exp(-2.8 * t);
    let sample = 0;
    for (let f = 0; f < freqs.length; f += 1) {
      const delay = f * 0.09;
      if (t < delay) continue;
      sample += Math.sin(2 * Math.PI * freqs[f]! * (t - delay)) * (1 / freqs.length);
    }
    data[i] = Math.max(-32767, Math.min(32767, Math.floor(sample * env * volume * 32767)));
  }
  const bytes = new ArrayBuffer(44 + data.length * 2);
  const view = new DataView(bytes);
  const writeStr = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + data.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, data.length * 2, true);
  for (let i = 0; i < data.length; i += 1) view.setInt16(44 + i * 2, data[i]!, true);
  const chars = Array.from(new Uint8Array(bytes), (b) => String.fromCharCode(b)).join("");
  return `data:audio/wav;base64,${btoa(chars)}`;
}

function ensureUrls(): void {
  if (!dingUrl) dingUrl = wavDataUrl([880, 1319], 0.5, 0.45);
  if (!dongUrl) dongUrl = wavDataUrl([349, 262, 196], 0.9, 0.55);
}

async function playUrl(url: string): Promise<void> {
  const el = new Audio(url);
  el.volume = 1;
  await el.play();
}

/** Create/resume audio under a user gesture so later status chimes are allowed. */
export function unlockNotifySounds(): void {
  ensureUrls();
  const audio = ensureCtx();
  void audio?.resume().catch(() => undefined);
  // Prime HTMLAudio under the gesture (required on Safari / Chrome autoplay).
  try {
    const warm = new Audio(dingUrl!);
    warm.volume = 0.001;
    void warm
      .play()
      .then(() => {
        warm.pause();
        warm.currentTime = 0;
      })
      .catch(() => undefined);
  } catch {
    // ignore
  }
}

/** Call once from the app so the first click unlocks audio. */
export function armNotifySounds(): void {
  if (typeof window === "undefined") return;
  unlockNotifySounds();
  if (armed) return;
  armed = true;
  const unlock = () => unlockNotifySounds();
  window.addEventListener("pointerdown", unlock, { passive: true });
  window.addEventListener("keydown", unlock, { passive: true });
}

export async function playDing(): Promise<void> {
  ensureUrls();
  try {
    await playUrl(dingUrl!);
  } catch {
    // Autoplay still blocked — next click will unlock.
  }
}

export async function playDong(): Promise<void> {
  ensureUrls();
  try {
    await playUrl(dongUrl!);
  } catch {
    // Autoplay still blocked — next click will unlock.
  }
}

export function playFeatureStatusSound(status: string | undefined): void {
  if (!status) return;
  if (status !== "paused" && status !== "completed" && status !== "failed") return;
  const now = Date.now();
  if (status === lastStatus && now - lastAt < 2000) return;
  lastStatus = status;
  lastAt = now;
  if (status === "failed") {
    void playDong();
    return;
  }
  void playDing();
}
