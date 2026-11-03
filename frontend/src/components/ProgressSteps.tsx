import { motion, useReducedMotion } from 'motion/react';

export const ANALYSIS_STEPS = [
  'Classifying…',
  'Checking market rates…',
  'Auditing markup…',
  'Scanning red flags…',
  'Synthesising verdict…',
] as const;

interface ProgressStepsProps {
  /** Index of the active step (0–4). Use 5 once every step is complete. */
  activeStep: number;
}

/**
 * Multi-stage progress stepper (PRD ANA-17). The active step pulses
 * via motion; completed steps turn solid emerald. Labels and stepper
 * semantics are unchanged. Progress is driven only by real SSE step
 * events (see App / analyzeCheckStream) — there is no client timer.
 */
export default function ProgressSteps({ activeStep }: ProgressStepsProps) {
  const reduceMotion = useReducedMotion();
  return (
    <ol
      aria-label="Analysis progress"
      aria-live="polite"
      className="rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4"
    >
      {ANALYSIS_STEPS.map((label, index) => {
        const done = index < activeStep;
        const active = index === activeStep;
        return (
          <li
            key={label}
            className="flex min-h-11 items-center gap-3 border-b border-[var(--border)] py-2 last:border-b-0"
          >
            <motion.span
              aria-hidden="true"
              className={[
                'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-bold',
                done
                  ? 'border-emerald-500 bg-emerald-500 text-stone-950'
                  : active
                    ? 'border-emerald-500 bg-emerald-500/15 text-emerald-400'
                    : 'border-[var(--border-strong)] bg-[var(--surface-inset)] text-[var(--text-muted)]',
              ].join(' ')}
              animate={
                active && !reduceMotion ? { scale: [1, 1.18, 1], opacity: [1, 0.75, 1] } : { scale: 1, opacity: 1 }
              }
              transition={
                active && !reduceMotion
                  ? { duration: 1.2, repeat: Infinity, ease: 'easeInOut' }
                  : { duration: 0.15 }
              }
            >
              {done ? '✓' : String(index + 1)}
            </motion.span>
            <span
              className={
                done || active
                  ? 'text-sm font-medium text-[var(--text-primary)]'
                  : 'text-sm text-[var(--text-muted)]'
              }
            >
              {label}
            </span>
            {active ? (
              <span className="ml-auto font-mono text-xs text-emerald-400">
                working…
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
