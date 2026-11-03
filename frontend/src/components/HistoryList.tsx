import { useEffect, useState } from 'react';
import type { ApiError, Category, VerdictResponse } from '../lib/api';
import { deleteCheck, listChecks, pinCheck } from '../lib/api';
import { VERDICT_STYLES } from './VerdictCard';

const CATEGORY_FILTERS: { value: string; label: string }[] = [
  { value: '', label: 'All categories' },
  { value: 'retail', label: 'Retail product' },
  { value: 'vehicle', label: 'Vehicle' },
  { value: 'property', label: 'Property / land' },
  { value: 'perishable', label: 'Perishable commodity' },
  { value: 'inventory', label: 'Inventory / stock' },
];

type GroupName = 'Today' | 'Yesterday' | 'Last 7 days' | 'Older';

function groupFor(createdAt: string, now: Date): GroupName {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return 'Older';
  const startOf = (d: Date) => {
    const copy = new Date(d);
    copy.setHours(0, 0, 0, 0);
    return copy.getTime();
  };
  const dayMs = 24 * 60 * 60 * 1000;
  const diffDays = Math.floor((startOf(now) - startOf(date)) / dayMs);
  if (diffDays <= 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays <= 7) return 'Last 7 days';
  return 'Older';
}

function formatWhen(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return createdAt;
  return date.toLocaleString();
}

const GROUP_ORDER: GroupName[] = ['Today', 'Yesterday', 'Last 7 days', 'Older'];

interface HistoryListProps {
  onSelect: (verdict: VerdictResponse) => void;
  onChanged: () => void;
}

export default function HistoryList({ onSelect, onChanged }: HistoryListProps) {
  const [items, setItems] = useState<VerdictResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState('');
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function load(selectedCategory: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await listChecks({
        limit: 20,
        offset: 0,
        category: selectedCategory || undefined,
      });
      setItems(result.items);
      setTotal(result.total);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Could not load history.',
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(category);
    // Load once per category change; `load` is stable enough for this view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category]);

  async function handleDelete(item: VerdictResponse) {
    const key = String(item.id);
    if (confirmingDeleteId !== key) {
      setConfirmingDeleteId(key);
      return;
    }
    setBusyId(key);
    setActionError(null);
    try {
      await deleteCheck(item.id);
      setItems((previous) => previous.filter((entry) => entry.id !== item.id));
      setTotal((previous) => Math.max(0, previous - 1));
      setConfirmingDeleteId(null);
      onChanged();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Could not delete this record.',
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handlePin(item: VerdictResponse) {
    const key = String(item.id);
    setBusyId(key);
    setActionError(null);
    try {
      const updated = await pinCheck(item.id);
      setItems((previous) =>
        previous.map((entry) => (entry.id === item.id ? updated : entry)),
      );
      onChanged();
    } catch (err) {
      const apiErr = err as ApiError;
      // Pin is a nice-to-have; if the backend rejects it, say so plainly.
      setActionError(
        err instanceof Error
          ? err.message
          : `Could not pin this record (${String(apiErr?.status ?? '')}).`,
      );
    } finally {
      setBusyId(null);
    }
  }

  const now = new Date();
  const groups = new Map<GroupName, VerdictResponse[]>();
  for (const item of items) {
    const group = groupFor(item.created_at, now);
    const existing = groups.get(group) ?? [];
    existing.push(item);
    groups.set(group, existing);
  }
  // Pinned records first within each group.
  for (const group of groups.values()) {
    group.sort((a, b) => Number(b.pinned === true) - Number(a.pinned === true));
  }

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-[22px] font-bold leading-snug text-[var(--text-primary)]">
            History
          </h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            <span className="font-mono text-[13px]">{total}</span> check
            {total === 1 ? '' : 's'} saved. Private checks never appear here.
          </p>
        </div>
        <div>
          <label
            className="mb-1 block text-sm font-semibold text-[var(--text-primary)]"
            htmlFor="history-category"
          >
            Category filter
          </label>
          <select
            id="history-category"
            value={category}
            onChange={(event) => {
              setCategory(event.target.value);
              setConfirmingDeleteId(null);
            }}
            className="min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-3 py-2 text-base text-[var(--text-primary)] transition-colors duration-150 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/50 focus:outline-none sm:w-56"
          >
            {CATEGORY_FILTERS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {actionError ? (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-red-500/40 bg-red-500/15 px-3 py-2.5 text-sm text-red-400"
        >
          {actionError}
        </p>
      ) : null}

      {loading ? (
        <div className="mt-4 space-y-3" aria-label="Loading history">
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              className="h-20 animate-pulse rounded-2xl border border-[var(--border)] bg-[var(--surface-card)]"
            />
          ))}
        </div>
      ) : error ? (
        <div
          role="alert"
          className="mt-4 rounded-2xl border border-red-500/40 bg-[var(--surface-card)] p-4"
        >
          <p className="text-sm text-red-400">{error}</p>
          <button
            type="button"
            onClick={() => void load(category)}
            className="mt-3 min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors duration-150 hover:border-[var(--border-strong)]"
          >
            Retry
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4">
          <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
            No checks yet
            {category
              ? ` in this category (${CATEGORY_FILTERS.find((f) => f.value === category)?.label ?? category}).`
              : '.'}{' '}
            Run a check and it will appear here — unless you used private mode.
          </p>
        </div>
      ) : (
        GROUP_ORDER.map((groupName) => {
          const groupItems = groups.get(groupName);
          if (!groupItems || groupItems.length === 0) return null;
          return (
            <section key={groupName} className="mt-6" aria-label={groupName}>
              <h3 className="text-lg font-semibold text-[var(--text-primary)]">
                {groupName}
              </h3>
              <ul className="mt-3 space-y-3">
                {groupItems.map((item) => {
                  const styles =
                    VERDICT_STYLES[item.verdict] ?? VERDICT_STYLES['Think Twice'];
                  const key = String(item.id);
                  const confirming = confirmingDeleteId === key;
                  const busy = busyId === key;
                  return (
                    <li
                      key={key}
                      className="rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4"
                    >
                      <div className="flex items-start gap-3">
                        <button
                          type="button"
                          onClick={() => onSelect(item)}
                          className="min-h-11 flex-1 text-left"
                          aria-label={`View verdict for ${item.title}`}
                        >
                          <span className="flex items-center gap-2">
                            <span
                              aria-hidden="true"
                              className={`h-2.5 w-2.5 shrink-0 rounded-full ${styles.dot}`}
                            />
                            <span className="text-base font-semibold text-[var(--text-primary)]">
                              {item.title}
                            </span>
                          </span>
                          <span className="mt-1 block text-sm text-[var(--text-secondary)]">
                            {item.location} · {item.verdict}
                            {item.pinned ? ' · Pinned' : ''}
                          </span>
                          <span className="mt-1 block font-mono text-xs text-[var(--text-muted)]">
                            {formatWhen(item.created_at)} ·{' '}
                            {(item.category as Category) ?? item.category}
                          </span>
                        </button>
                        <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
                          <button
                            type="button"
                            onClick={() => void handlePin(item)}
                            disabled={busy}
                            aria-pressed={item.pinned === true}
                            className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors duration-150 hover:border-[var(--border-strong)] disabled:opacity-50"
                          >
                            {item.pinned ? 'Pinned' : 'Pin'}
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDelete(item)}
                            disabled={busy}
                            className={
                              confirming
                                ? 'min-h-11 rounded-lg border border-red-500/40 bg-red-500/15 px-3 py-2 text-sm font-semibold text-red-400'
                                : 'min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors duration-150 hover:border-red-500/40 hover:text-red-400 disabled:opacity-50'
                            }
                          >
                            {busy
                              ? 'Working…'
                              : confirming
                                ? 'Confirm delete?'
                                : 'Delete'}
                          </button>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })
      )}
    </div>
  );
}
