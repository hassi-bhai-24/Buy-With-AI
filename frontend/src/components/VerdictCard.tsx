import { useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import type { VerdictResponse, VerdictTier } from '../lib/api';
import {
  createWatchlist,
  downloadCheckSummary,
  formatMoney,
  formatNumber,
  getShare,
} from '../lib/api';
import CashFlowTable from './CashFlowTable';
import Checklist from './Checklist';
import RedFlags from './RedFlags';

/** Verdict tier colours, exactly per design system §2.3. */
export const VERDICT_STYLES: Record<
  VerdictTier,
  { badge: string; dot: string; icon: string }
> = {
  'Great Buy': {
    badge: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-400',
    dot: 'bg-emerald-500',
    icon: '✓',
  },
  'Good Buy': {
    badge: 'border-teal-500/40 bg-teal-500/15 text-teal-400',
    dot: 'bg-teal-500',
    icon: '✓',
  },
  'Think Twice': {
    badge: 'border-amber-500/40 bg-amber-500/15 text-amber-400',
    dot: 'bg-amber-500',
    icon: '!',
  },
  Risky: {
    badge: 'border-orange-500/40 bg-orange-500/15 text-orange-400',
    dot: 'bg-orange-500',
    icon: '!',
  },
  Avoid: {
    badge: 'border-red-500/40 bg-red-500/15 text-red-400',
    dot: 'bg-red-500',
    icon: '✕',
  },
};

const CATEGORY_LABELS: Record<string, string> = {
  retail: 'Retail product',
  vehicle: 'Vehicle',
  property: 'Property / land',
  perishable: 'Perishable commodity',
  inventory: 'Inventory / stock',
};

function engineLabel(engine: VerdictResponse['engine']): string {
  if (engine === 'rule-based') return 'Engine: rule-based';
  if (engine === 'ollama') return 'Engine: ollama (local model)';
  return `Engine: ${engine}`;
}

/**
 * Honest price-source labelling: a baseline must never be presented
 * as live market data.
 */
function priceSourceLabel(source: VerdictResponse['price_source']): string {
  if (source === 'live scrape') return 'Prices: live scrape';
  if (source === 'baseline') return 'Prices: baseline (cached/seed estimate)';
  if (source === 'estimate') return 'Prices: estimate — not live market data';
  return `Prices: ${source}`;
}

function formatCheckedAt(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return createdAt;
  return date.toLocaleString();
}

interface VerdictCardProps {
  verdict: VerdictResponse;
  onCheckAnother: () => void;
  onDelete: () => Promise<void> | void;
  /** Open the chat view with a thread linked to this check. */
  onDiscuss?: (verdict: VerdictResponse) => void;
}

export default function VerdictCard({
  verdict,
  onCheckAnother,
  onDelete,
  onDiscuss,
}: VerdictCardProps) {
  const reduceMotion = useReducedMotion();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const [watchOpen, setWatchOpen] = useState(false);
  const [targetPrice, setTargetPrice] = useState(
    String(verdict.counter_offers.target),
  );
  const [watchBusy, setWatchBusy] = useState(false);
  const [watchMessage, setWatchMessage] = useState<string | null>(null);
  const [watchError, setWatchError] = useState<string | null>(null);
  const [shareMessage, setShareMessage] = useState<string | null>(null);
  const [shareText, setShareText] = useState<string | null>(null);
  const [downloadMessage, setDownloadMessage] = useState<string | null>(null);

  const styles = VERDICT_STYLES[verdict.verdict] ?? VERDICT_STYLES['Think Twice'];
  const bandCurrency = verdict.price_band?.currency;
  const markup = verdict.brand_markup;
  let markupPct = markup?.markup_percentage;
  if (
    markup &&
    (!Number.isFinite(markupPct) || markupPct === undefined) &&
    markup.retail_asking_price > 0
  ) {
    markupPct =
      ((markup.retail_asking_price - markup.estimated_making_cost) /
        markup.retail_asking_price) *
      100;
  }
  const markupPctClamped =
    markupPct !== undefined && Number.isFinite(markupPct)
      ? Math.min(100, Math.max(0, markupPct))
      : null;
  const makingPct =
    markupPctClamped === null ? null : 100 - markupPctClamped;

  async function handleDelete() {
    if (!confirmingDelete) {
      setConfirmingDelete(true);
      return;
    }
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
      setConfirmingDelete(false);
    }
  }

  function buildSummary(): string {
    const lines: string[] = [
      `Buy with AI verdict: ${verdict.verdict}`,
      verdict.title,
      verdict.location,
      '',
      verdict.plain_truth,
      '',
    ];
    if (verdict.price_band) {
      lines.push(
        `Fair price band (${verdict.price_band.currency}/${verdict.price_band.unit}): ` +
          `${formatNumber(verdict.price_band.min_price)} – ${formatNumber(verdict.price_band.max_price)}, expected ${formatNumber(verdict.price_band.expected_price)}.`,
      );
    }
    lines.push(
      `Counter-offers: opening ${formatMoney(verdict.counter_offers.opening, bandCurrency)}, ` +
        `target ${formatMoney(verdict.counter_offers.target, bandCurrency)}, ` +
        `walk away above ${formatMoney(verdict.counter_offers.walk_away, bandCurrency)}.`,
    );
    if (verdict.red_flags.length > 0) {
      lines.push('', 'Red flags:', ...verdict.red_flags.map((flag) => `- ${flag}`));
    }
    lines.push('', 'Estimates only — not financial or legal advice.');
    return lines.join('\n');
  }

  async function handleCopy() {
    setCopyError(false);
    try {
      await navigator.clipboard.writeText(buildSummary());
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopyError(true);
    }
  }

  async function handleWatchPrice() {
    const target = Number(targetPrice);
    if (!Number.isFinite(target) || target <= 0) {
      setWatchError('Enter a target price greater than 0.');
      return;
    }
    setWatchBusy(true);
    setWatchError(null);
    setWatchMessage(null);
    try {
      await createWatchlist({ check_id: verdict.id, target_price: target });
      setWatchMessage('Watching this price. See the Watchlist view to recheck it.');
      setWatchOpen(false);
    } catch (err) {
      setWatchError(err instanceof Error ? err.message : 'Could not add this watch.');
    } finally {
      setWatchBusy(false);
    }
  }

  async function handleShare() {
    setShareMessage(null);
    setShareText(null);
    // The backend returns a relative URL ("/check/{id}"); resolve it
    // to an absolute URL for the share sheet / clipboard.
    function absoluteUrl(url: string): string {
      if (/^https?:\/\//i.test(url)) return url;
      return new URL(url, window.location.href).toString();
    }
    try {
      const share = await getShare(verdict.id);
      const url = absoluteUrl(share.url);
      const text = `${share.text}\n${url}`;
      if (typeof navigator.share === 'function') {
        await navigator.share({ title: verdict.title, text: share.text, url });
        setShareMessage('Shared.');
        return;
      }
      await navigator.clipboard.writeText(text);
      setShareMessage('Share link copied to clipboard.');
    } catch (err) {
      // A cancelled share sheet is not an error worth alarming about;
      // anything else falls back to showing the text for manual copy.
      if (err instanceof DOMException && err.name === 'AbortError') return;
      try {
        const share = await getShare(verdict.id);
        setShareText(`${share.text}\n${absoluteUrl(share.url)}`);
        setShareMessage('Sharing is unavailable here — copy the text below manually.');
      } catch {
        setShareMessage(err instanceof Error ? err.message : 'Sharing failed.');
      }
    }
  }

  async function handleDownload(format: 'txt' | 'md') {
    setDownloadMessage(null);
    try {
      await downloadCheckSummary(verdict.id, format);
      setDownloadMessage(`Summary downloaded as .${format}.`);
    } catch (err) {
      setDownloadMessage(err instanceof Error ? err.message : 'Download failed.');
    }
  }

  return (
    <motion.article
      initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.2, ease: 'easeOut' }}
      className="verdict-print-area rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4"
    >
      {/* Hero: verdict first (PRD VER-1/VER-3). */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-sm text-[var(--text-secondary)]">
          📍 {verdict.location}
          {verdict.pinned ? (
            <span className="ml-2 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-2 py-0.5 text-xs font-bold text-[var(--text-primary)]">
              Pinned
            </span>
          ) : null}
        </p>
        <span
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2 text-sm font-bold tracking-wide uppercase ${styles.badge}`}
        >
          <span aria-hidden="true">{styles.icon}</span>
          {verdict.verdict}
        </span>
      </div>

      <h2 className="mt-3 text-[28px] leading-tight font-bold text-[var(--text-primary)]">
        {verdict.title}
      </h2>
      <p className="mt-1 text-sm text-[var(--text-secondary)]">
        {CATEGORY_LABELS[verdict.category] ?? verdict.category}
        {' · '}
        <span className="font-mono text-[13px]">
          Checked: {formatCheckedAt(verdict.created_at)}
        </span>
      </p>

      <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-4">
        <h3 className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
          The Plain Truth
        </h3>
        <p className="mt-2 text-base leading-relaxed text-[var(--text-primary)]">
          {verdict.plain_truth}
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2" aria-label="Verdict provenance">
        <span className="rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-2.5 py-1.5 text-xs font-semibold text-[var(--text-primary)]">
          {engineLabel(verdict.engine)}
        </span>
        <span className="rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-2.5 py-1.5 text-xs font-semibold text-[var(--text-primary)]">
          {priceSourceLabel(verdict.price_source)}
        </span>
        <span className="rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-2.5 py-1.5 text-xs font-semibold text-[var(--text-primary)]">
          Confidence: {verdict.confidence}
        </span>
      </div>

      <section aria-label="Evidence quality" className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-4">
        <h3 className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
          Evidence quality
        </h3>
        <p className="mt-2 text-sm font-semibold text-[var(--text-primary)]">
          {verdict.evidence_quality ?? 'limited'}
        </p>
        {verdict.price_band &&
        ((verdict.price_band.usable_sample_count ?? 0) > 0 ||
          (verdict.price_band.dropped_sample_count ?? 0) > 0) ? (
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Usable samples: {verdict.price_band.usable_sample_count ?? 0}
            {' · '}
            Dropped samples: {verdict.price_band.dropped_sample_count ?? 0}
          </p>
        ) : null}
        {(verdict.missing_evidence ?? []).length > 0 ? (
          <div className="mt-3">
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              What we don&apos;t know
            </p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm leading-relaxed text-[var(--text-secondary)]">
              {(verdict.missing_evidence ?? []).map((item, index) => (
                <li key={`${index}-${item}`}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {(verdict.evidence_notes ?? []).length > 0 ? (
          <ul className="mt-2 space-y-1 text-sm leading-relaxed text-[var(--text-secondary)]">
            {(verdict.evidence_notes ?? []).map((note, index) => (
              <li key={`${index}-${note}`}>{note}</li>
            ))}
          </ul>
        ) : null}
      </section>

      {verdict.price_band ? (
        <section aria-label="Fair price band" className="mt-6">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">
            Fair price band
          </h3>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-4">
              <p className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
                Min
              </p>
              <p className="mt-1 font-mono text-[13px] font-medium text-[var(--text-primary)]">
                {formatMoney(verdict.price_band.min_price, bandCurrency)}
                <span className="text-[var(--text-secondary)]">/{verdict.price_band.unit}</span>
              </p>
            </div>
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 p-4">
              <p className="text-[11px] font-bold tracking-wide text-emerald-400 uppercase">
                Expected
              </p>
              <p className="mt-1 font-mono text-[13px] font-medium text-[var(--text-primary)]">
                {formatMoney(verdict.price_band.expected_price, bandCurrency)}
                <span className="text-[var(--text-secondary)]">/{verdict.price_band.unit}</span>
              </p>
            </div>
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-4">
              <p className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
                Max
              </p>
              <p className="mt-1 font-mono text-[13px] font-medium text-[var(--text-primary)]">
                {formatMoney(verdict.price_band.max_price, bandCurrency)}
                <span className="text-[var(--text-secondary)]">/{verdict.price_band.unit}</span>
              </p>
            </div>
          </div>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            Source: {verdict.price_band.source}
          </p>
        </section>
      ) : null}

      {markup && markupPctClamped !== null && makingPct !== null ? (
        <section aria-label="Brand markup breakdown" className="mt-6">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">
            Making cost vs. brand markup
          </h3>
          <div
            className="mt-3 flex h-8 w-full overflow-hidden rounded-lg border border-[var(--border)]"
            role="img"
            aria-label={`Estimated making cost ${formatNumber(makingPct)} percent, brand markup ${formatNumber(markupPctClamped)} percent`}
          >
            <div
              className="h-full bg-emerald-500 transition-all duration-150"
              style={{ width: `${makingPct}%` }}
            />
            <div
              className="h-full bg-amber-500 transition-all duration-150"
              style={{ width: `${markupPctClamped}%` }}
            />
          </div>
          <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
            Manufacturing:{' '}
            <span className="font-mono text-[13px] text-[var(--text-primary)]">
              {formatMoney(markup.estimated_making_cost, bandCurrency)}
            </span>{' '}
            | Brand premium:{' '}
            <span className="font-mono text-[13px] text-[var(--text-primary)]">
              {formatMoney(
                markup.retail_asking_price - markup.estimated_making_cost,
                bandCurrency,
              )}{' '}
              ({formatNumber(markupPctClamped)}%)
            </span>
          </p>
          {markup.notes ? (
            <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
              {markup.notes}
            </p>
          ) : null}
        </section>
      ) : null}

      {verdict.cash_flow ? (
        <div className="mt-6">
          <CashFlowTable
            cashFlow={verdict.cash_flow}
            currency={bandCurrency}
          />
        </div>
      ) : null}

      {verdict.spoilage ? (
        <section aria-label="Spoilage estimate" className="mt-6">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">
            Spoilage estimate
          </h3>
          <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            {(
              [
                [
                  'Salable',
                  `${formatNumber(verdict.spoilage.salable_quantity)} ${verdict.price_band?.unit ?? ''}`.trim(),
                ],
                ['Spoilage', `${formatNumber(verdict.spoilage.spoilage_loss_percent)}%`],
                [
                  'Decay rate',
                  `${formatNumber(verdict.spoilage.lambda_per_hour)} / hour`,
                ],
                ['Hours to sell', formatNumber(verdict.spoilage.hours_to_sell)],
                [
                  'Transit damage',
                  `${formatNumber(verdict.spoilage.transit_damage_fraction * 100)}%`,
                ],
                [
                  'Temperature',
                  `${formatNumber(verdict.spoilage.temperature_c)}°C${verdict.spoilage.temperature_assumed ? ' (assumed)' : ''}`,
                ],
              ] as const
            ).map(([term, value]) => (
              <div
                key={term}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-3"
              >
                <dt className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
                  {term}
                </dt>
                <dd className="mt-1 font-mono text-[13px] font-medium text-[var(--text-primary)]">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          {(verdict.spoilage.assumptions ?? []).length > 0 ? (
            <div className="mt-3">
              <p className="text-sm font-semibold text-[var(--text-primary)]">
                Assumptions
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm leading-relaxed text-[var(--text-secondary)]">
                {(verdict.spoilage.assumptions ?? []).map((item, index) => (
                  <li key={`${index}-${item}`}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2">
        <RedFlags flags={verdict.red_flags} />
        <Checklist
          items={verdict.verify_checklist}
          idPrefix={String(verdict.id)}
        />
      </div>

      <section aria-label="Counter-offer bracket" className="mt-6">
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          Counter-offer bracket
        </h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-4">
            <p className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
              Opening offer
            </p>
            <p className="mt-1 font-mono text-[13px] font-medium text-[var(--text-primary)]">
              {formatMoney(verdict.counter_offers.opening, bandCurrency)}
            </p>
          </div>
          <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/15 p-4">
            <p className="text-[11px] font-bold tracking-wide text-emerald-400 uppercase">
              Target price
            </p>
            <p className="mt-1 font-mono text-[13px] font-medium text-[var(--text-primary)]">
              {formatMoney(verdict.counter_offers.target, bandCurrency)}
            </p>
          </div>
          <div className="rounded-lg border border-red-500/40 bg-red-500/15 p-4">
            <p className="text-[11px] font-bold tracking-wide text-red-400 uppercase">
              Walk away above
            </p>
            <p className="mt-1 font-mono text-[13px] font-medium text-[var(--text-primary)]">
              {formatMoney(verdict.counter_offers.walk_away, bandCurrency)}
            </p>
          </div>
        </div>
      </section>

      {verdict.next_steps.length > 0 ? (
        <section aria-label="Next steps" className="mt-6">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">Next steps</h3>
          <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-[var(--text-primary)]">
            {verdict.next_steps.map((step, index) => (
              <li key={`${index}-${step}`}>{step}</li>
            ))}
          </ol>
        </section>
      ) : null}

      {verdict.sources_cited.length > 0 ? (
        <section aria-label="Sources cited" className="mt-6">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">
            Sources cited
          </h3>
          <ul className="mt-3 space-y-1.5 text-sm leading-relaxed text-[var(--text-secondary)]">
            {verdict.sources_cited.map((source, index) => (
              <li key={`${index}-${source}`} className="break-words">
                {source}
              </li>
            ))}
          </ul>
          <p className="mt-2 font-mono text-xs text-[var(--text-muted)]">
            Checked: {formatCheckedAt(verdict.created_at)}
          </p>
        </section>
      ) : null}

      <div className="no-print mt-6 flex flex-col gap-2 border-t border-[var(--border)] pt-4 sm:flex-row">
        <button
          type="button"
          onClick={onCheckAnother}
          disabled={deleting}
          className="min-h-11 flex-1 rounded-lg bg-emerald-500 px-4 py-3 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
        >
          Check Another Deal
        </button>
        <button
          type="button"
          onClick={handleCopy}
          disabled={deleting}
          className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-3 text-base font-semibold text-[var(--text-primary)] transition-colors duration-150 hover:border-[var(--border-strong)] disabled:opacity-50"
        >
          {copied ? 'Copied!' : 'Copy summary'}
        </button>
        <button
          type="button"
          onClick={handleDelete}
          disabled={deleting}
          className={
            confirmingDelete
              ? 'min-h-11 rounded-lg border border-red-500/40 bg-red-500/15 px-4 py-3 text-base font-semibold text-red-400 transition-colors duration-150'
              : 'min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-3 text-base font-semibold text-[var(--text-primary)] transition-colors duration-150 hover:border-red-500/40 hover:text-red-400 disabled:opacity-50'
          }
        >
          {deleting
            ? 'Deleting…'
            : confirmingDelete
              ? 'Confirm delete?'
              : 'Delete record'}
        </button>
      </div>
      {copyError ? (
        <p role="alert" className="mt-2 text-sm text-amber-400">
          Copy failed. Select the verdict text and copy it manually.
        </p>
      ) : null}

      {/* Secondary actions: watch, share, print, download, discuss. */}
      <div className="no-print mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            setWatchOpen((value) => !value);
            setWatchError(null);
          }}
          disabled={deleting}
          aria-expanded={watchOpen}
          className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-base font-semibold text-[var(--text-primary)] hover:border-[var(--border-strong)] disabled:opacity-50"
        >
          Watch price
        </button>
        <button
          type="button"
          onClick={() => void handleShare()}
          disabled={deleting}
          className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-base font-semibold text-[var(--text-primary)] hover:border-[var(--border-strong)] disabled:opacity-50"
        >
          Share
        </button>
        <button
          type="button"
          onClick={() => window.print()}
          disabled={deleting}
          className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-base font-semibold text-[var(--text-primary)] hover:border-[var(--border-strong)] disabled:opacity-50"
        >
          Print / Save as PDF
        </button>
        <button
          type="button"
          onClick={() => void handleDownload('txt')}
          disabled={deleting}
          className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-base font-semibold text-[var(--text-primary)] hover:border-[var(--border-strong)] disabled:opacity-50"
        >
          Download summary (.txt)
        </button>
        <button
          type="button"
          onClick={() => void handleDownload('md')}
          disabled={deleting}
          className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-base font-semibold text-[var(--text-primary)] hover:border-[var(--border-strong)] disabled:opacity-50"
        >
          Download summary (.md)
        </button>
        {onDiscuss ? (
          <button
            type="button"
            onClick={() => onDiscuss(verdict)}
            disabled={deleting}
            className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-base font-semibold text-[var(--text-primary)] hover:border-[var(--border-strong)] disabled:opacity-50"
          >
            Discuss this check
          </button>
        ) : null}
      </div>
      {watchOpen ? (
        <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-3">
          <label
            className="mb-1 block text-sm font-semibold text-[var(--text-primary)]"
            htmlFor="watch-target-price"
          >
            Target price ({verdict.price_band?.currency ?? 'PKR'})
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="watch-target-price"
              type="number"
              min="0"
              step="any"
              inputMode="decimal"
              value={targetPrice}
              onChange={(event) => setTargetPrice(event.target.value)}
              disabled={watchBusy}
              className="min-h-11 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-card)] px-3 py-2 font-mono text-base text-[var(--text-primary)] focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/50 focus:outline-none disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => void handleWatchPrice()}
              disabled={watchBusy}
              className="min-h-11 rounded-lg bg-emerald-500 px-4 py-2 text-base font-bold text-stone-950 hover:bg-emerald-600 disabled:opacity-50"
            >
              {watchBusy ? 'Adding…' : 'Add to watchlist'}
            </button>
          </div>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            Checked in the app only — no email or push alerts.
          </p>
          {watchError ? (
            <p role="alert" className="mt-2 text-sm text-red-400">
              {watchError}
            </p>
          ) : null}
        </div>
      ) : null}
      {watchMessage ? (
        <p role="status" className="mt-2 text-sm text-[var(--text-secondary)]">
          {watchMessage}
        </p>
      ) : null}
      {shareMessage ? (
        <p role="status" className="mt-2 text-sm text-[var(--text-secondary)]">
          {shareMessage}
        </p>
      ) : null}
      {shareText ? (
        <p className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-3 text-sm break-words whitespace-pre-wrap text-[var(--text-primary)]">
          {shareText}
        </p>
      ) : null}
      {downloadMessage ? (
        <p role="status" className="mt-2 text-sm text-[var(--text-secondary)]">
          {downloadMessage}
        </p>
      ) : null}
      {confirmingDelete && !deleting ? (
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          This permanently deletes the record. Press “Confirm delete?” again to
          delete, or “Check Another Deal” to keep it.
        </p>
      ) : null}
      <p className="mt-4 text-sm leading-relaxed text-[var(--text-muted)]">
        Estimates only — not financial or legal advice. Verify prices and
        documents yourself before paying.
      </p>
    </motion.article>
  );
}
