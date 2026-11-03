import { useState } from 'react';

interface RedFlagsProps {
  flags: string[];
}

/**
 * Red flags: the top 3 are prominent; any further flags sit behind a
 * "show all" control (PRD ANA-4).
 */
export default function RedFlags({ flags }: RedFlagsProps) {
  const [expanded, setExpanded] = useState(false);

  if (flags.length === 0) {
    return (
      <section aria-label="Red flags">
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">Red flags</h3>
        <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
          No red flags were returned for this check.
        </p>
      </section>
    );
  }

  const top = flags.slice(0, 3);
  const rest = flags.slice(3);
  const visible = expanded ? flags : top;

  return (
    <section aria-label="Red flags">
      <h3 className="text-lg font-semibold text-[var(--text-primary)]">
        Red flags{' '}
        <span className="font-mono text-[13px] font-medium text-[var(--text-secondary)]">
          {flags.length}
        </span>
      </h3>
      <ul className="mt-3 space-y-2">
        {visible.map((flag, index) => (
          <li
            key={`${index}-${flag}`}
            className={
              index < 3
                ? 'flex gap-3 rounded-lg border border-red-500/40 bg-red-500/15 px-3 py-2.5 text-sm leading-relaxed text-[var(--text-primary)]'
                : 'flex gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-3 py-2.5 text-sm leading-relaxed text-[var(--text-secondary)]'
            }
          >
            <span aria-hidden="true" className="shrink-0">
              ⚠
            </span>
            <span>{flag}</span>
          </li>
        ))}
      </ul>
      {rest.length > 0 ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="mt-3 min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors duration-150 hover:border-[var(--border-strong)]"
        >
          {expanded
            ? 'Show fewer flags'
            : `Show ${rest.length} more flag${rest.length === 1 ? '' : 's'}`}
        </button>
      ) : null}
    </section>
  );
}
