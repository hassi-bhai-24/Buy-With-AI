import type { CashFlow, CashFlowCase } from '../lib/api';
import { formatMoney, formatNumber } from '../lib/api';

interface CashFlowTableProps {
  cashFlow: CashFlow;
  currency?: string;
}

function CaseCard({
  heading,
  headingClass,
  cashCase,
  currency,
}: {
  heading: string;
  headingClass: string;
  cashCase: CashFlowCase;
  currency?: string;
}) {
  const profit = cashCase.net_profit_loss;
  const profitClass = profit < 0 ? 'text-red-400' : 'text-emerald-400';
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-4">
      <h4 className={`text-sm font-bold tracking-wide ${headingClass}`}>
        {heading}
      </h4>
      <p className={`mt-2 font-mono text-[13px] font-medium ${profitClass}`}>
        {profit < 0 ? '−' : '+'}
        {formatMoney(Math.abs(profit), currency)}
      </p>
      <dl className="mt-3 space-y-1 text-sm text-[var(--text-secondary)]">
        <div className="flex justify-between gap-3">
          <dt>Turnover</dt>
          <dd className="font-mono text-[13px] text-[var(--text-primary)]">
            {cashCase.turnover_rate}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt>Spoilage / loss</dt>
          <dd className="font-mono text-[13px] text-[var(--text-primary)]">
            {formatNumber(cashCase.spoilage_loss_percent)}%
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
        {cashCase.rationale}
      </p>
      <p className="mt-2 font-mono text-xs text-[var(--text-muted)]">
        {cashCase.scenario_name}
      </p>
    </div>
  );
}

/** 3-tier cash flow table: Best / Expected / Worst (design system §4.3). */
export default function CashFlowTable({ cashFlow, currency }: CashFlowTableProps) {
  return (
    <section aria-label="Cash flow scenarios">
      <h3 className="text-lg font-semibold text-[var(--text-primary)]">Cash flow</h3>
      <p className="mt-1 text-sm text-[var(--text-secondary)]">
        Projected figures based on the assumptions in the spoilage
        section — not guaranteed.
      </p>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        <CaseCard
          heading="BEST CASE"
          headingClass="text-emerald-400"
          cashCase={cashFlow.best_case}
          currency={currency}
        />
        <CaseCard
          heading="EXPECTED CASE"
          headingClass="text-[var(--text-primary)]"
          cashCase={cashFlow.expected_case}
          currency={currency}
        />
        <CaseCard
          heading="WORST CASE"
          headingClass="text-red-400"
          cashCase={cashFlow.worst_case}
          currency={currency}
        />
      </div>
    </section>
  );
}
