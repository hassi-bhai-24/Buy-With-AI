import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import type { VerdictResponse } from '../lib/api';
import { listChecks } from '../lib/api';
import type { Theme } from '../lib/theme';

export interface DrawerNavItem {
  view: string;
  label: string;
  icon: string;
}

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  view: string;
  items: DrawerNavItem[];
  onNavigate: (view: string) => void;
  theme: Theme;
  onToggleTheme: () => void;
}

interface HistorySummary {
  total: number;
  recent: VerdictResponse[];
}

/**
 * Left sliding drawer (design system §5.1/§6): navigation, theme
 * toggle and a history summary. Overlay + backdrop on all sizes.
 * Esc closes, backdrop click closes, focus moves into the drawer on
 * open and returns to the trigger on close (the trigger is focused
 * by the close handler in App). Slide: 250ms, [0.16, 1, 0.3, 1].
 */
export default function Drawer({
  open,
  onClose,
  view,
  items,
  onNavigate,
  theme,
  onToggleTheme,
}: DrawerProps) {
  const panelRef = useRef<HTMLElement | null>(null);
  const reduceMotion = useReducedMotion();
  const [summary, setSummary] = useState<HistorySummary | null>(null);
  const [summaryError, setSummaryError] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  // History summary is fetched lazily, only when the drawer opens,
  // so a backend that has not landed the new checks shape yet does
  // not affect the main view.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setSummaryLoading(true);
    setSummaryError(false);
    void listChecks({ limit: 3, offset: 0 })
      .then((result) => {
        if (!cancelled) {
          setSummary({ total: result.total, recent: result.items });
        }
      })
      .catch(() => {
        if (!cancelled) setSummaryError(true);
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open ]);

  const slide = reduceMotion
    ? { duration: 0 }
    : { duration: 0.25, ease: [0.16, 1, 0.3, 1] as const };
  const offscreenX = reduceMotion ? 0 : -320;

  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.div
            key="drawer-backdrop"
            aria-hidden="true"
            className="fixed inset-0 z-40 bg-black/60"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.25 }}
            onClick={onClose}
          />
          <motion.aside
            key="drawer-panel"
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
            tabIndex={-1}
            className="fixed top-0 bottom-0 left-0 z-50 flex w-[300px] max-w-[85vw] flex-col overflow-y-auto border-r border-[var(--border)] bg-[var(--surface-card)] px-4 py-4 text-[var(--text-primary)] outline-none"
            initial={{ x: offscreenX }}
            animate={{ x: 0 }}
            exit={{ x: offscreenX }}
            transition={slide}
          >
            <div className="flex min-h-11 items-center justify-between gap-3">
              <p className="text-[22px] leading-tight font-bold">Buy with AI</p>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close menu"
                className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-3 py-2 text-base font-semibold text-[var(--text-primary)]"
              >
                ✕
              </button>
            </div>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              Check before you pay. A verdict, with numbers.
            </p>

            <nav aria-label="Drawer navigation" className="mt-6 flex flex-col gap-1">
              {items.map((item) => (
                <button
                  key={item.view}
                  type="button"
                  onClick={() => onNavigate(item.view)}
                  aria-current={view === item.view ? 'page' : undefined}
                  className={[
                    'flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 text-base font-semibold',
                    view === item.view
                      ? 'bg-emerald-500/15 text-emerald-400'
                      : 'text-[var(--text-primary)] hover:bg-[var(--surface-secondary)]',
                  ].join(' ')}
                >
                  <span aria-hidden="true" className="font-mono text-sm">
                    {item.icon}
                  </span>
                  {item.label}
                </button>
              ))}
            </nav>

            <div className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--surface-inset)] p-4">
              <h2 className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
                Appearance
              </h2>
              <button
                type="button"
                onClick={onToggleTheme}
                aria-label={
                  theme === 'light'
                    ? 'Switch to dark mode'
                    : 'Switch to light mode'
                }
                aria-pressed={theme === 'light'}
                className="mt-3 flex min-h-11 w-full items-center justify-between rounded-lg border border-[var(--border-strong)] bg-[var(--surface-card)] px-3 py-2 text-base font-semibold text-[var(--text-primary)]"
              >
                <span>{theme === 'light' ? '☀ Light mode' : '☾ Dark mode'}</span>
                <span aria-hidden="true" className="text-sm">
                  {theme === 'light' ? 'On' : 'Off'}
                </span>
              </button>
              <p className="mt-2 text-sm text-[var(--text-secondary)]">
                Dark is the default. Your choice is saved on this device.
              </p>
            </div>

            <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-inset)] p-4">
              <h2 className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
                History summary
              </h2>
              {summaryLoading ? (
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  Loading…
                </p>
              ) : summaryError ? (
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  History is unavailable right now. Open History to retry.
                </p>
              ) : summary ? (
                <>
                  <p className="mt-2 text-sm text-[var(--text-secondary)]">
                    <span className="font-mono text-[13px] text-[var(--text-primary)]">
                      {summary.total}
                    </span>{' '}
                    check{summary.total === 1 ? '' : 's'} saved.
                  </p>
                  {summary.recent.length > 0 ? (
                    <ul className="mt-2 space-y-2">
                      {summary.recent.map((item) => (
                        <li key={String(item.id)}>
                          <button
                            type="button"
                            onClick={() => onNavigate('history')}
                            className="min-h-11 w-full rounded-lg px-2 py-2 text-left text-sm text-[var(--text-primary)] hover:bg-[var(--surface-secondary)]"
                          >
                            <span className="block font-semibold">{item.title}</span>
                            <span className="block text-[var(--text-secondary)]">
                              {item.location} · {item.verdict}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-sm text-[var(--text-secondary)]">
                      No checks yet.
                    </p>
                  )}
                </>
              ) : null}
            </div>

            <p className="mt-auto pt-6 text-sm text-[var(--text-secondary)]">
              Local Data Sovereignty • Zero Tracking • Delete Anytime
            </p>
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  );
}
