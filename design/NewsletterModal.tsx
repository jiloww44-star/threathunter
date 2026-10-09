/**
 * NewsletterModal.tsx — accessible companion to NewsletterModal.module.css.
 *
 * Implements the JS-side items flagged in the CSS audit:
 *  - `role="dialog"` + `aria-modal` + labelled-by
 *  - focus trap (Tab cycles inside; initial focus on the email input)
 *  - Esc closes; page scroll is locked while open; focus restored on close
 *  - close button has an explicit `aria-label`; status is a live region
 */
import { useEffect, useRef, useState } from "react";
import styles from "./NewsletterModal.module.css";

interface Props {
  open: boolean;
  onClose: () => void;
  onSubscribe: (email: string) => Promise<void> | void;
}

export function NewsletterModal({ open, onClose, onSubscribe }: Props) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<{ kind: "error" | "success" | null; text: string }>({
    kind: null,
    text: "",
  });
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const prevActive = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";           // scroll lock
    inputRef.current?.focus();                          // initial focus

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && boxRef.current) {          // focus trap
        const focusables = boxRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          last?.focus();
          e.preventDefault();
        } else if (!e.shiftKey && document.activeElement === last) {
          first?.focus();
          e.preventDefault();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      prevActive?.focus();                              // restore focus
    };
  }, [open, onClose]);

  if (!open) return null;

  const submit = async () => {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setStatus({ kind: "error", text: "Enter a valid email address." });
      return;
    }
    try {
      await onSubscribe(email);
      setStatus({ kind: "success", text: "You're on the list — welcome." });
    } catch {
      setStatus({ kind: "error", text: "Something went wrong. Try again later." });
    }
  };

  return (
    <div className={styles.overlay} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={boxRef} className={styles.container}
           role="dialog" aria-modal="true" aria-labelledby="nl-title"
           aria-describedby="nl-copy">
        <button type="button" className={styles.closeButton}
                aria-label="Close signup dialog" onClick={onClose}>
          ×
        </button>

        <div className={styles.left}>
          <p className={styles.leftKicker}>The Brief</p>
          <h2 id="nl-title" className={styles.title}>Signal, not noise.</h2>
          <p id="nl-copy" className={styles.copy}>
            One evidence-graded briefing each week. No spam, unsubscribe anytime.
          </p>
          <form className={styles.form}
                onSubmit={(e) => { e.preventDefault(); void submit(); }}>
            <label htmlFor="nl-email" className={styles.visuallyHidden}>
              Email address
            </label>
            <input ref={inputRef} id="nl-email" type="email" required
                   className={styles.input} placeholder="you@example.com"
                   value={email} onChange={(e) => setEmail(e.target.value)}
                   autoComplete="email" />
            <button type="submit" className={styles.button}>Subscribe</button>
          </form>
          <p role="status" aria-live="polite"
             className={`${styles.status} ${
               status.kind === "error" ? styles.statusError
               : status.kind === "success" ? styles.statusSuccess : ""}`}>
            {status.text}
          </p>
        </div>

        <div className={styles.right}>
          <p className={styles.rightKicker}>Weekly</p>
          <p className={styles.rightTitle}>Read what matters.</p>
          <div className={styles.rightRule} aria-hidden="true" />
          <p className={styles.rightMeta}>Fridays · 5 min read · No ads</p>
        </div>
      </div>
    </div>
  );
}
