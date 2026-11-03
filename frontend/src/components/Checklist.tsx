import { useState } from 'react';

interface ChecklistProps {
  items: string[];
  idPrefix: string;
}

/** Interactive "verify before paying" checklist (PRD VER-4). */
export default function Checklist({ items, idPrefix }: ChecklistProps) {
  const [checked, setChecked] = useState<ReadonlySet<number>>(new Set());

  function toggle(index: number) {
    setChecked((previous) => {
      const next = new Set(previous);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  if (items.length === 0) {
    return (
      <section aria-label="Verify before paying checklist">
        <h3 className="text-lg font-semibold text-[var(--text-primary)]">
          Verify before paying
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
          No checklist items were returned for this check.
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Verify before paying checklist">
      <h3 className="text-lg font-semibold text-[var(--text-primary)]">
        Verify before paying{' '}
        <span className="font-mono text-[13px] font-medium text-[var(--text-secondary)]">
          {checked.size}/{items.length} checked
        </span>
      </h3>
      <ul className="mt-3 space-y-2">
        {items.map((item, index) => {
          const id = `${idPrefix}-check-${index}`;
          const isChecked = checked.has(index);
          return (
            <li key={id}>
              <label
                htmlFor={id}
                className="flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-3 py-2.5 text-sm leading-relaxed text-[var(--text-primary)] transition-colors duration-150 hover:border-[var(--border-strong)]"
              >
                <input
                  id={id}
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggle(index)}
                  className="mt-0.5 h-5 w-5 shrink-0 accent-emerald-500"
                />
                <span className={isChecked ? 'text-[var(--text-secondary)] line-through' : ''}>
                  {item}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
