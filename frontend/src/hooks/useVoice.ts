// Voice interaction — spec Part 11 (§18). Voice is an adapter over the same
// API. Demo profile: Web Speech API STT/TTS in-browser; the backend provides
// /voice/spoken-summary for the spoken response text. Everything degrades
// gracefully to text when speech is unavailable (§20).
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void;
  onend: () => void;
  onerror: () => void;
  start: () => void;
  stop: () => void;
}

declare global {
  interface Window {
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    SpeechRecognition?: new () => SpeechRecognitionLike;
  }
}

export function useVoice(onTranscript: (t: string) => void) {
  const [listening, setListening] = useState(false);
  const supported =
    typeof window !== "undefined" &&
    Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  const recRef = useRef<SpeechRecognitionLike | null>(null);

  const start = useCallback(() => {
    if (!supported) return;
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition!;
    const rec = new Ctor();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = false;
    rec.onresult = (e) => {
      const first = e.results[0] as ArrayLike<{ transcript: string }> | undefined;
      const text = first?.[0]?.transcript;
      if (text) onTranscript(text);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    rec.start();
    setListening(true);
  }, [onTranscript, supported]);

  const stop = useCallback(() => {
    recRef.current?.stop();
    setListening(false);
  }, []);

  useEffect(() => () => recRef.current?.stop(), []);

  return { listening, start, stop, supported };
}

/** Fetch the spoken-summary variant and play it with client TTS. §19 speaks
 * verdict → confidence → answer → contradictions → action. */
export async function speakResult(result: Record<string, unknown>): Promise<void> {
  try {
    const { spoken_text } = await api.spokenSummary(result);
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(spoken_text);
      u.rate = 1.0;
      window.speechSynthesis.speak(u);
    }
  } catch {
    /* TTS unavailable — visual result remains complete (§20) */
  }
}

export function stopSpeaking() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}
