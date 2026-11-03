import { useCallback, useEffect, useRef, useState } from 'react';
import type { AnalyzeRequest, HealthResponse, VerdictResponse } from './lib/api';
import { analyzeCheckStream, deleteCheck, getHealth } from './lib/api';
import {
  getCurrentTheme,
  persistTheme,
  applyTheme,
  toggleThemeValue,
} from './lib/theme';
import type { Theme } from './lib/theme';
import ChatPanel from './components/ChatPanel';
import DecisionForm from './components/DecisionForm';
import Drawer from './components/Drawer';
import HistoryList from './components/HistoryList';
import ProgressSteps from './components/ProgressSteps';
import ToolsPanel from './components/ToolsPanel';
import VerdictCard from './components/VerdictCard';
import WatchlistView from './components/WatchlistView';

export type View = 'check' | 'history' | 'tools' | 'watchlist' | 'chat';

const NAV_ITEMS: { view: View; label: string; icon: string }[] = [
  { view: 'check', label: 'Check', icon: '✓' },
  { view: 'history', label: 'History', icon: '▤' },
  { view: 'tools', label: 'Tools', icon: '∑' },
  { view: 'watchlist', label: 'Watchlist', icon: '☆' },
  { view: 'chat', label: 'Chat', icon: '✉' },
];

export default function App() {
  const [view, setView] = useState<View>('check');
  const [verdict, setVerdict] = useState<VerdictResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [activeStep, setActiveStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [online, setOnline] = useState(
    typeof navigator === 'undefined' ? true : navigator.onLine,
  );
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);
  const [theme, setTheme] = useState<Theme>(() => getCurrentTheme());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pendingDiscuss, setPendingDiscuss] = useState<VerdictResponse | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const hamburgerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    function handleOnline() {
      setOnline(true);
    }
    function handleOffline() {
      setOnline(false);
    }
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void getHealth()
      .then((result) => {
        if (!cancelled) {
          setHealth(result);
          setHealthError(false);
        }
      })
      .catch(() => {
        if (!cancelled) setHealthError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleToggleTheme() {
    const next = toggleThemeValue(theme);
    setTheme(next);
    applyTheme(next);
    persistTheme(next);
  }

  function closeDrawer() {
    setDrawerOpen(false);
    // Focus returns to the hamburger button that opened the drawer.
    hamburgerRef.current?.focus();
  }

  function handleDrawerNavigate(next: string) {
    setDrawerOpen(false);
    setView(next as View);
    window.scrollTo(0, 0);
  }

  const handlePendingConsumed = useCallback(() => {
    setPendingDiscuss(null);
  }, []);

  function handleDiscuss(check: VerdictResponse) {
    setPendingDiscuss(check);
    setView('chat');
    window.scrollTo(0, 0);
  }

  async function handleAnalyze(payload: AnalyzeRequest) {
    if (analyzing) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setAnalyzing(true);
    setActiveStep(0);
    setError(null);
    setNotice(null);
    setVerdict(null);
    try {
      // Progress is driven only by real SSE step events from the
      // backend (step N -> index N-1); no client-side timer.
      const result = await analyzeCheckStream(
        payload,
        controller.signal,
        (step) => setActiveStep(Math.min(4, Math.max(0, step - 1))),
      );
      setActiveStep(5);
      setVerdict(result);
      setView('check');
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setNotice('Check cancelled. Nothing was changed.');
      } else {
        setError(err instanceof Error ? err.message : 'Check failed.');
      }
    } finally {
      setAnalyzing(false);
      abortRef.current = null;
    }
  }

  function handleCancel() {
    abortRef.current?.abort();
  }

  function handleCheckAnother() {
    setVerdict(null);
    setError(null);
    setNotice(null);
    window.scrollTo(0, 0);
  }

  async function handleDeleteVerdict() {
    if (!verdict) return;
    await deleteCheck(verdict.id);
    setVerdict(null);
    setHistoryKey((key) => key + 1);
    setNotice('Record deleted.');
  }

  function handleSelectFromHistory(selected: VerdictResponse) {
    setVerdict(selected);
    setError(null);
    setNotice(null);
    setView('check');
    window.scrollTo(0, 0);
  }

  function goTo(next: View) {
    setView(next);
    window.scrollTo(0, 0);
  }

  const navButtonClass = (itemView: View) =>
    [
      'flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 text-base font-semibold transition-colors duration-150',
      view === itemView
        ? 'bg-emerald-500/15 text-emerald-400'
        : 'text-[var(--text-primary)] hover:bg-[var(--surface-secondary)]',
    ].join(' ');

  const themeToggle = (
    <button
      type="button"
      onClick={handleToggleTheme}
      aria-label={
        theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'
      }
      aria-pressed={theme === 'light'}
      className="flex min-h-11 items-center gap-2 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)]"
    >
      <span aria-hidden="true">{theme === 'light' ? '☀' : '☾'}</span>
      <span className="hidden sm:inline">
        {theme === 'light' ? 'Light' : 'Dark'}
      </span>
    </button>
  );

  return (
    <div className="flex min-h-screen flex-col bg-[var(--surface-canvas)] text-[var(--text-primary)]">
      {/* Header (all sizes): hamburger opens the drawer, theme toggle. */}
      <header className="flex min-h-14 items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--surface-card)] px-4">
        <div className="flex min-h-11 items-center gap-2">
          <button
            ref={hamburgerRef}
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open menu"
            aria-expanded={drawerOpen}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-3 py-2 text-base font-bold text-[var(--text-primary)]"
          >
            ☰
          </button>
          <p className="text-lg font-bold">Buy with AI</p>
        </div>
        <div className="flex items-center gap-2">
          {themeToggle}
          <span className="hidden rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-2.5 py-1.5 font-mono text-xs text-[var(--text-primary)] sm:inline">
            Bahawalpur · PKR
          </span>
        </div>
      </header>

      <Drawer
        open={drawerOpen}
        onClose={closeDrawer}
        view={view}
        items={NAV_ITEMS}
        onNavigate={handleDrawerNavigate}
        theme={theme}
        onToggleTheme={handleToggleTheme}
      />

      <div className="flex min-w-0 flex-1">
        {/* Desktop sidebar */}
        <aside className="hidden w-72 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-card)] px-4 py-4 md:flex lg:w-80">
          <p className="text-[28px] leading-tight font-bold">Buy with AI</p>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Check before you pay. A verdict, with numbers.
          </p>
          <nav aria-label="Main navigation" className="mt-6 flex flex-col gap-1">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.view}
                type="button"
                onClick={() => goTo(item.view)}
                aria-current={view === item.view ? 'page' : undefined}
                className={navButtonClass(item.view)}
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
              Backend status
            </h2>
            {health ? (
              <dl className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between gap-3">
                  <dt className="text-[var(--text-secondary)]">Status</dt>
                  <dd className="font-mono text-[13px]">{health.status}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[var(--text-secondary)]">Engine</dt>
                  <dd className="font-mono text-[13px]">{health.engine}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[var(--text-secondary)]">Ollama</dt>
                  <dd className="font-mono text-[13px]">
                    {health.ollama_available ? 'available' : 'unavailable'}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-[var(--text-secondary)]">Version</dt>
                  <dd className="font-mono text-[13px]">{health.version}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-2 text-sm text-[var(--text-secondary)]">
                {healthError
                  ? 'Backend unreachable at http://127.0.0.1:8000 (via /api proxy). Checks will fail until it is running.'
                  : 'Checking backend…'}
              </p>
            )}
          </div>
          <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-inset)] p-4">
            <h2 className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
              Location defaults
            </h2>
            <p className="mt-2 font-mono text-[13px] text-[var(--text-primary)]">
              Pakistan · Punjab · Bahawalpur · PKR
            </p>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              Change them on any check. They are form defaults, not a saved
              profile.
            </p>
          </div>
          <p className="mt-auto pt-6 text-sm text-[var(--text-secondary)]">
            Local Data Sovereignty • Zero Tracking • Delete Anytime
          </p>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col pb-20 md:pb-0">
          {!online ? (
            <div
              role="alert"
              className="border-b border-amber-500/40 bg-amber-500/15 px-4 py-3 text-sm leading-relaxed text-amber-400"
            >
              You are offline. Live price checks need a connection and the
              backend; this build stores no cached baselines locally, so checks
              cannot run until you are back online.
            </div>
          ) : null}

          <main className="mx-auto w-full max-w-[960px] flex-1 px-4 py-4 md:py-6">
            {notice ? (
              <p
                role="status"
                className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--surface-card)] px-3 py-2.5 text-sm text-[var(--text-primary)]"
              >
                {notice}
              </p>
            ) : null}
            {error ? (
              <p
                role="alert"
                className="mb-4 rounded-lg border border-red-500/40 bg-red-500/15 px-3 py-2.5 text-sm leading-relaxed text-red-400"
              >
                {error}
              </p>
            ) : null}

            {view === 'check' ? (
              <>
                {!verdict ? (
                  <DecisionForm
                    submitting={analyzing}
                    onSubmit={(payload) => void handleAnalyze(payload)}
                    onCancel={handleCancel}
                  />
                ) : null}
                {analyzing ? (
                  <div className="mt-4 space-y-4">
                    <ProgressSteps activeStep={activeStep} />
                    <div aria-label="Loading verdict" className="space-y-3">
                      <div className="h-32 animate-pulse rounded-2xl border border-[var(--border)] bg-[var(--surface-card)]" />
                      <div className="h-24 animate-pulse rounded-2xl border border-[var(--border)] bg-[var(--surface-card)]" />
                      <div className="h-24 animate-pulse rounded-2xl border border-[var(--border)] bg-[var(--surface-card)]" />
                    </div>
                  </div>
                ) : null}
                {verdict && !analyzing ? (
                  <VerdictCard
                    verdict={verdict}
                    onCheckAnother={handleCheckAnother}
                    onDelete={handleDeleteVerdict}
                    onDiscuss={handleDiscuss}
                  />
                ) : null}
              </>
            ) : null}

            {view === 'history' ? (
              <HistoryList
                key={historyKey}
                onSelect={handleSelectFromHistory}
                onChanged={() => setHistoryKey((key) => key + 1)}
              />
            ) : null}

            {view === 'tools' ? <ToolsPanel /> : null}

            {view === 'watchlist' ? <WatchlistView /> : null}

            {view === 'chat' ? (
              <ChatPanel
                pendingCheck={pendingDiscuss}
                onPendingConsumed={handlePendingConsumed}
              />
            ) : null}

            <footer className="mt-8 rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4">
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                Settings &amp; about
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                Location defaults: Pakistan, Punjab, Bahawalpur, currency PKR.
                Change them on any check — they are form defaults, not a saved
                profile.
              </p>
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                Local Data Sovereignty • Zero Tracking • Delete Anytime
              </p>
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                Verdicts are estimates based on the data available at check
                time. They are not financial or legal advice. Prices labelled
                “baseline” are cached or seed estimates, never live market
                data. Verify prices, documents, and the item itself before
                paying.
              </p>
              <p className="mt-2 font-mono text-xs leading-relaxed text-[var(--text-muted)]">
                {health
                  ? `Backend: ${health.status} · Engine: ${health.engine} · Ollama: ${health.ollama_available ? 'available' : 'unavailable'} · v${health.version}`
                  : 'Backend: status unknown — the app talks to http://127.0.0.1:8000 through the /api proxy.'}
              </p>
            </footer>
          </main>
        </div>
      </div>

      {/* Mobile bottom navigation */}
      <nav
        aria-label="Main navigation"
        className="fixed inset-x-0 bottom-0 z-10 flex border-t border-[var(--border)] bg-[var(--surface-card)] px-2 py-1 md:hidden"
      >
        {NAV_ITEMS.map((item) => (
          <button
            key={item.view}
            type="button"
            onClick={() => goTo(item.view)}
            aria-current={view === item.view ? 'page' : undefined}
            className={`flex min-h-11 flex-1 flex-col items-center justify-center rounded-lg px-1 py-1 text-[11px] font-semibold transition-colors duration-150 ${
              view === item.view
                ? 'bg-emerald-500/15 text-emerald-400'
                : 'text-[var(--text-primary)]'
            }`}
          >
            <span aria-hidden="true" className="font-mono text-sm leading-none">
              {item.icon}
            </span>
            <span className="mt-0.5">{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
