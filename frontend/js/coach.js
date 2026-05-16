// Coach modal: fetch 3 Socratic questions from /api/coach, optionally
// record a voice reflection that gets saved as an `idea` node.

import { VoiceRecorder, uploadAudio } from "./voice.js";
import { api } from "./api.js";

const $ = (id) => document.getElementById(id);

let recorder = null;

export async function openCoach() {
  $("coach-modal").classList.remove("hidden");
  $("coach-loading").classList.remove("hidden");
  $("coach-questions").classList.add("hidden");
  $("coach-actions").classList.add("hidden");
  $("coach-error").classList.add("hidden");

  try {
    const res = await fetch("/api/coach", { method: "POST" });
    if (!res.ok) {
      let d;
      try { d = (await res.json()).detail; } catch { d = res.statusText; }
      throw new Error(d || "coach failed");
    }
    const { questions } = await res.json();
    renderQuestions(questions);
  } catch (e) {
    $("coach-loading").classList.add("hidden");
    const err = $("coach-error");
    err.textContent = "Не получилось: " + e.message;
    err.classList.remove("hidden");
    $("coach-actions").classList.remove("hidden");
  }
}

function renderQuestions(questions) {
  const ol = $("coach-questions");
  ol.innerHTML = "";
  for (const q of questions) {
    const li = document.createElement("li");
    li.textContent = q;
    ol.appendChild(li);
  }
  $("coach-loading").classList.add("hidden");
  ol.classList.remove("hidden");
  $("coach-actions").classList.remove("hidden");
}

export function closeCoach() {
  $("coach-modal").classList.add("hidden");
  if (recorder && recorder.state === "recording") recorder.cancel();
  setMicState("idle", "Записать ответ голосом");
}

function setMicState(s, label) {
  const btn = $("coach-mic");
  btn.dataset.state = s;
  if (label != null) $("coach-mic-label").textContent = label;
}

export async function toggleCoachMic() {
  if (!recorder) {
    recorder = new VoiceRecorder((s) => {
      if (s === "recording") setMicState("recording", "Стоп");
      else if (s === "processing") setMicState("processing", "Сохраняю…");
      else setMicState("idle", "Записать ответ голосом");
    });
  }

  if (recorder.state === "idle") {
    try { await recorder.start(); }
    catch (e) {
      alert("Микрофон недоступен: " + e.message);
      recorder.reset();
    }
    return;
  }

  if (recorder.state === "recording") {
    try {
      const blob = await recorder.stop();
      const { text } = await uploadAudio(blob);
      if (!text) {
        setMicState("idle", "Не расслышал — ещё раз");
        return;
      }
      // Reflection goes directly as an idea, not through the parser.
      const title = text.length > 80 ? text.slice(0, 77) + "…" : text;
      await api.createNode({
        type: "idea",
        title,
        status: "active",
        context: text,
        tags: ["рефлексия"],
      });
      setMicState("idle", "Готово ✓");
      setTimeout(closeCoach, 800);
    } catch (e) {
      alert("Не удалось сохранить: " + e.message);
    } finally {
      recorder.reset();
    }
  }
}
