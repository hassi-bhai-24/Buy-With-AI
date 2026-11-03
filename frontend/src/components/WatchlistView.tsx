import { useEffect, useState } from 'react';
import type { WatchlistItem, WatchlistRecheck } from '../lib/api';
import {
  deleteWatchlist,
  formatMoney,
  formatNumber,
  formatToolValue,
  listWatchlist,
  prettifyKey,
  recheckWatchlist,
} from '../lib/api';

/**
 * Watchlist view: in-app price flags only. No email or push copy
 * anywhere — rechecking just compares the latest expected price
 * against the target here, in the app.
 */
export default function WatchlistView() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rechecks, setRechecks] = useState<Record<string, WatchlistRecheck>>({});

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await listWatchlist());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load watchlist.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleDelete(item: WatchlistItem) {
    const key = String(item.id);
    if (confirmingDeleteId !== key) {
      setConfirmingDeleteId(key);
      return;
    }
    setBusyId(key);
    setActionError(null);
    try {
      await deleteWatchlist(item.id);
      setItems((previous) => previous.filter((entry) => entry.id !== item.id));
      setConfirmingDeleteId(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Could not remove this watch.');
    } finally {
      setBusyId(null);
    }
  }

  async function handleRecheck(item: WatchlistItem) {
    const key = String(item.id);
    setBusyId(key);
    setActionError(null);
    try {
      const result = await recheckWatchlist(item.id);
      setRechecks((previous) => ({ ...previous, [key]: result }));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Recheck failed.');
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <h2 className="text-[22px] font-bold leading-snug text-[var(--text-primary)]">
        Watchlist
      </h2>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
        Prices you are watching, checked here in the app. Add a watch from a
        verdict with “Watch price”. Nothing is emailed or pushed.
      </p>

      {actionError ? (
        <p role="alert" className="mt-4 rounded-lg border border-red-500/40 bg-red-500/15 px-3 py-2.5 text-sm text-red-400">
          {actionError}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-4 space-y-3" aria-label="Loading watchlist">
          {[0, 1].map((index) => (
            <div
              key={index}
              className="h-20 animate-pulse rounded-2xl border border-[var(--border)] bg-[var(--surface-card)]"
            />
          ))}
        </div>
      ) : error ? (
        <div role="alert" className="mt-4 rounded-2xl border border-red-500/40 bg-[var(--surface-card)] p-4">
          <p className="text-sm text-red-400">{error}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-3 min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-sm font-semibold text-[var(--text-primary)]"
          >
            Retry
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4">
          <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
            No watched prices yet. Run a check, then use “Watch price” on its
            verdict to watch a target price here.
          </p>
        </div>
      ) : (
        <ul className="mt-4 space-y-3">
          {items.map((item) => {
            const key = String(item.id);
            const confirming = confirmingDeleteId === key;
            const busy = busyId === key;
            const recheck = rechecks[key];
            return (
              <li
                key={key}
                className="rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4"
              >
                <p className="text-base font-semibold text-[var(--text-primary)]">{item.title}</p>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  Target:{' '}
                  <span className="font-mono text-[13px] text-[var(--text-primary)]">
                    {formatMoney(item.target_price, item.currency)}
                  </span>
                  {' · '}
                  <span className="font-mono text-xs">
                    Added {new Date(item.created_at).toLocaleString()}
                  </span>
                </p>
                {recheck ? (
                  <dl className="mt-3 space-y-1 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-3">
                    <div className="flex items-baseline justify-between gap-3">
                      <dt className="text-sm text-[var(--text-secondary)]">Current expected price</dt>
                      <dd className="font-mono text-[13px] font-medium text-[var(--text-primary)]">
                        {recheck.current_expected_price === null
                          ? 'Not available — no fresh baseline'
                          : `${formatNumber(recheck.current_expected_price)} ${item.currency}`}
                      </dd>
                    </div>
                    <div className="flex items-baseline justify-between gap-3">
                      <dt className="text-sm text-[var(--text-secondary)]">Target met</dt>
                      <dd className="font-mono text-[13px] font-medium text-[var(--text-primary)]">
                        {recheck.target_met ? 'Yes' : 'No'}
                      </dd>
                    </div>
                    <div className="flex items-baseline justify-between gap-3">
                      <dt className="text-sm text-[var(--text-secondary)]">Price source</dt>
                      <dd className="font-mono text-[13px] font-medium text-[var(--text-primary)]">
                        {recheck.price_source}
                      </dd>
                    </div>
                    {recheck.note ? (
                      <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                        {recheck.note}
                      </p>
                    ) : null}
                    {recheck.band !== undefined && recheck.band !== null && typeof recheck.band !== 'object' ? (
                      <div className="flex items-baseline justify-between gap-3">
                        <dt className="text-sm text-[var(--text-secondary)]">Band</dt>
                        <dd className="font-mono text-[13px] font-medium break-all text-[var(--text-primary)]">
                          {formatToolValue(recheck.band)}
                        </dd>
                      </div>
                    ) : null}
                    {recheck.band !== undefined && recheck.band !== null && typeof recheck.band === 'object' ? (
                      <div className="mt-1">
                        {Object.entries(recheck.band as Record<string, unknown>).map(([k, v]) => (
                          <div key={k} className="flex items-baseline justify-between gap-3">
                            <dt className="text-sm text-[var(--text-secondary)]">{prettifyKey(k)}</dt>
                            <dd className="font-mono text-[13px] font-medium text-[var(--text-primary)]">
                              {formatToolValue(v)}
                            </dd>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </dl>
                ) : null}
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={() => void handleRecheck(item)}
                    disabled={busy}
                    className="min-h-11 rounded-lg bg-emerald-500 px-4 py-2 text-base font-bold text-stone-950 hover:bg-emerald-600 disabled:opacity-50"
                  >
                    {busy ? 'Checking…' : 'Recheck price'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(item)}
                    disabled={busy}
                    className={
                      confirming
                        ? 'min-h-11 rounded-lg border border-red-500/40 bg-red-500/15 px-4 py-2 text-base font-semibold text-red-400'
                        : 'min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-base font-semibold text-[var(--text-primary)] hover:border-red-500/40 hover:text-red-400 disabled:opacity-50'
                    }
                  >
                    {busy ? 'Working…' : confirming ? 'Confirm remove?' : 'Remove'}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
