import { useState } from 'react';
import type { FormEvent } from 'react';
import type { BarcodeResult } from '../lib/api';
import { lookupBarcode } from '../lib/api';

const inputClass =
  'min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-3 py-2 text-base text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/50 focus:outline-none disabled:opacity-50';

interface BarcodeLookupProps {
  disabled?: boolean;
  /** Current description, so we never silently overwrite typed text. */
  descriptionEmpty: boolean;
  onFillDescription: (text: string) => void;
}

function isValidDigits(value: string): boolean {
  return /^(?:\d{8}|\d{13})$/.test(value);
}

/**
 * Barcode lookup (Open Food Facts, via the backend). Digits are
 * validated client-side (8 or 13) before any request. On a hit the
 * product name fills the description for the user to confirm before
 * analysing; on a miss the UI says plainly that it was not found.
 */
export default function BarcodeLookup({
  disabled,
  descriptionEmpty,
  onFillDescription,
}: BarcodeLookupProps) {
  const [digits, setDigits] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BarcodeResult | null>(null);
  const [filled, setFilled] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = digits.trim();
    if (!isValidDigits(value)) {
      setError('Enter 8 or 13 digits — no letters, spaces, or hyphens.');
      setResult(null);
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setFilled(false);
    try {
      const found = await lookupBarcode(value);
      setResult(found);
      if (found.found && found.product_name) {
        if (descriptionEmpty) {
          onFillDescription(found.product_name);
          setFilled(true);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Barcode lookup failed.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <section aria-label="Barcode lookup" className="mt-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">
        Barcode lookup
      </h3>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
        Enter the digits printed under a product barcode. Product details
        come from Open Food Facts via the backend.
      </p>
      <form onSubmit={handleSubmit} className="mt-2 flex flex-col gap-2 sm:flex-row">
        <label className="sr-only" htmlFor="barcode-digits">
          Barcode digits (8 or 13)
        </label>
        <input
          id="barcode-digits"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={digits}
          onChange={(event) => setDigits(event.target.value)}
          disabled={disabled || loading}
          placeholder="e.g. 3017620422003"
          className={`${inputClass} font-mono sm:flex-1`}
        />
        <button
          type="submit"
          disabled={disabled || loading}
          className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2 text-base font-semibold text-[var(--text-primary)] hover:border-[var(--border-strong)] disabled:opacity-50"
        >
          {loading ? 'Looking up…' : 'Look up barcode'}
        </button>
      </form>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-400">
          {error}
        </p>
      ) : null}
      {result ? (
        result.found ? (
          <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-3">
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {result.product_name ?? 'Product found, but no name was returned.'}
            </p>
            <p className="mt-1 font-mono text-xs text-[var(--text-secondary)]">
              Barcode {result.barcode} · Source: {result.source}
              {result.nutriscore ? ` · Nutri-Score ${result.nutriscore}` : ''}
            </p>
            {result.ingredients ? (
              <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                Ingredients: {result.ingredients}
              </p>
            ) : null}
            {result.product_name ? (
              filled ? (
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  Description filled with the product name — edit it before
                  checking.
                </p>
              ) : (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    onFillDescription(result.product_name as string);
                    setFilled(true);
                  }}
                  className="mt-2 min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-card)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] disabled:opacity-50"
                >
                  Fill description with product name
                </button>
              )
            ) : null}
          </div>
        ) : (
          <p role="status" className="mt-2 text-sm text-[var(--text-secondary)]">
            Not found: no product with barcode {result.barcode} in Open Food
            Facts. Type the item description yourself.
          </p>
        )
      ) : null}
    </section>
  );
}
