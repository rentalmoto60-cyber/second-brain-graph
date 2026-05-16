// Browser MediaRecorder wrapper. Three states: idle / recording / processing.
// onStateChange receives the new state for UI updates.

export class VoiceRecorder {
  constructor(onStateChange) {
    this.onStateChange = onStateChange || (() => {});
    this.state = "idle";
    this.mediaRecorder = null;
    this.chunks = [];
    this.stream = null;
  }

  _setState(s) { this.state = s; this.onStateChange(s); }

  async start() {
    if (this.state !== "idle") return;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Браузер не поддерживает запись звука");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    this.mediaRecorder = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
    this.chunks = [];
    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) this.chunks.push(e.data);
    };
    this.mediaRecorder.start();
    this._setState("recording");
  }

  stop() {
    return new Promise((resolve, reject) => {
      if (this.state !== "recording" || !this.mediaRecorder) {
        return reject(new Error("not recording"));
      }
      this.mediaRecorder.onstop = () => {
        const type = this.mediaRecorder.mimeType || "audio/webm";
        const blob = new Blob(this.chunks, { type });
        this._cleanup();
        this._setState("processing");
        resolve(blob);
      };
      this.mediaRecorder.stop();
    });
  }

  cancel() {
    if (this.mediaRecorder && this.state === "recording") {
      try { this.mediaRecorder.stop(); } catch {}
    }
    this._cleanup();
    this._setState("idle");
  }

  reset() { this._setState("idle"); }

  _cleanup() {
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    this.mediaRecorder = null;
  }
}

export async function uploadAudio(blob) {
  const fd = new FormData();
  const ext = (blob.type.includes("webm") ? "webm" : "ogg");
  fd.append("audio", blob, `thought.${ext}`);
  const res = await fetch("/api/voice", { method: "POST", body: fd });
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
    throw new Error(detail || "voice upload failed");
  }
  return res.json();  // { text: "..." }
}

export async function submitThought(text) {
  const res = await fetch("/api/thoughts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
    throw new Error(detail || "thought submission failed");
  }
  return res.json();  // { node, parsed, needs_review }
}
