import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import type { ToolResponse } from '../lib/api';
import {
  brandMarkupTool,
  convertCurrencyTool,
  convertLandTool,
  discountValidatorTool,
  expenseLeakageTool,
  formatToolValue,
  installmentAuditTool,
  marginTool,
  prettifyKey,
  savingsGoalTool,
} from '../lib/api';

const inputClass =
  'min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-3 py-2 text-base text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-colors duration-150 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/50 focus:outline-none disabled:opacity-50';

const labelClass = 'mb-1 block text-sm font-semibold text-[var(--text-primary)]';

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label className={labelClass} htmlFor={id}>
        {label}
      </label>
      {children}
    </div>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
  placeholder,
  required = true,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <Field id={id} label={label}>
      <input
        id={id}
        type="number"
        required={required}
        step="any"
        inputMode="decimal"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={`${inputClass} font-mono`}
      />
    </Field>
  );
}

/**
 * Generic result rendering: every numeric field the backend returns is
 * shown as `label + monospace value`, so extra fields survive untouched.
 */
function ToolResultView({ result }: { result: ToolResponse | null }) {
  if (result === null) return null;
  const entries = Object.entries(result).filter(
    ([, value]) => value !== null && value !== undefined,
  );
  if (entries.length === 0) {
    return <p className="mt-3 text-sm text-[var(--text-secondary)]">No result fields returned.</p>;
  }
  return (
    <dl className="mt-3 space-y-2 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-4">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-baseline justify-between gap-3">
          <dt className="text-sm text-[var(--text-secondary)]">{prettifyKey(key)}</dt>
          <dd className="font-mono text-[13px] font-medium break-all text-[var(--text-primary)]">
            {formatToolValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

interface ToolState {
  loading: boolean;
  error: string | null;
  result: ToolResponse | null;
}

const idleState: ToolState = { loading: false, error: null, result: null };

function useToolRunner(
  run: () => Promise<ToolResponse>,
): [ToolState, (event: FormEvent<HTMLFormElement>) => void] {
  const [state, setState] = useState<ToolState>(idleState);
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState({ loading: true, error: null, result: null });
    try {
      const result = await run();
      setState({ loading: false, error: null, result });
    } catch (err) {
      setState({
        loading: false,
        error: err instanceof Error ? err.message : 'Tool request failed.',
        result: null,
      });
    }
  }
  return [state, handleSubmit];
}

function ToolCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4">
      <h3 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h3>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">{description}</p>
      {children}
    </section>
  );
}

function ToolFooter({ state }: { state: ToolState }) {
  return (
    <>
      {state.error ? (
        <p role="alert" className="mt-3 text-sm text-red-400">
          {state.error}
        </p>
      ) : null}
      {state.loading ? (
        <div
          className="mt-3 h-16 animate-pulse rounded-lg border border-[var(--border)] bg-[var(--surface-inset)]"
          aria-label="Calculating"
        />
      ) : null}
      <ToolResultView result={state.result} />
    </>
  );
}

const LAND_UNITS = ['marla', 'kanal', 'sqft', 'acre', 'hectare'] as const;

const CURRENCIES = ['PKR', 'USD', 'INR', 'GBP', 'EUR', 'AED'] as const;

interface ExpenseRow {
  name: string;
  amount: string;
  category: string;
}

/** Essential categories per the backend rule; all others are discretionary. */
const EXPENSE_CATEGORIES = [
  'housing',
  'utilities',
  'groceries',
  'transport',
  'health',
  'education',
  'dining',
  'entertainment',
  'subscriptions',
  'shopping',
  'other',
] as const;

export default function ToolsPanel() {
  const [costPerUnit, setCostPerUnit] = useState('');
  const [sellingPrice, setSellingPrice] = useState('');
  const [quantity, setQuantity] = useState('');
  const [fixedCosts, setFixedCosts] = useState('');
  const [marginState, runMargin] = useToolRunner(() =>
    marginTool({
      cost_per_unit: Number(costPerUnit),
      selling_price: Number(sellingPrice),
      quantity: Number(quantity),
      ...(fixedCosts.trim() !== '' ? { fixed_costs: Number(fixedCosts) } : {}),
    }),
  );

  const [landValue, setLandValue] = useState('');
  const [fromUnit, setFromUnit] = useState<string>('marla');
  const [toUnit, setToUnit] = useState<string>('sqft');
  const [marlaStandard, setMarlaStandard] = useState('225');
  const [landState, runLand] = useToolRunner(() =>
    convertLandTool({
      value: Number(landValue),
      from_unit: fromUnit,
      to_unit: toUnit,
      marla_standard: marlaStandard,
    }),
  );

  const [cashPrice, setCashPrice] = useState('');
  const [downPayment, setDownPayment] = useState('');
  const [monthlyInstallment, setMonthlyInstallment] = useState('');
  const [months, setMonths] = useState('');
  const [installmentState, runInstallment] = useToolRunner(() =>
    installmentAuditTool({
      cash_price: Number(cashPrice),
      down_payment: Number(downPayment),
      monthly_installment: Number(monthlyInstallment),
      months: Number(months),
    }),
  );

  const [makingCost, setMakingCost] = useState('');
  const [askingPrice, setAskingPrice] = useState('');
  const [markupState, runMarkup] = useToolRunner(() =>
    brandMarkupTool({
      making_cost: Number(makingCost),
      retail_price: Number(askingPrice),
    }),
  );

  const [convertAmount, setConvertAmount] = useState('');
  const [convertFrom, setConvertFrom] = useState('PKR');
  const [convertTo, setConvertTo] = useState('USD');
  const [convertState, runConvert] = useToolRunner(() =>
    convertCurrencyTool({
      amount: Number(convertAmount),
      from_currency: convertFrom,
      to_currency: convertTo,
    }),
  );

  const [goalTarget, setGoalTarget] = useState('');
  const [goalCurrent, setGoalCurrent] = useState('');
  const [goalDeposit, setGoalDeposit] = useState('');
  const [goalMonths, setGoalMonths] = useState('');
  const [goalState, runGoal] = useToolRunner(() =>
    savingsGoalTool({
      target_amount: Number(goalTarget),
      ...(goalCurrent.trim() !== ''
        ? { current_savings: Number(goalCurrent) }
        : {}),
      ...(goalDeposit.trim() !== ''
        ? { monthly_deposit: Number(goalDeposit) }
        : {}),
      ...(goalMonths.trim() !== '' ? { months: Number(goalMonths) } : {}),
    }),
  );

  const [leakIncome, setLeakIncome] = useState('');
  const [leakRows, setLeakRows] = useState<ExpenseRow[]>([
    { name: '', amount: '', category: 'groceries' },
  ]);
  const [leakState, runLeak] = useToolRunner(() =>
    expenseLeakageTool({
      income: Number(leakIncome),
      expenses: leakRows
        .filter((row) => row.name.trim() !== '' && row.amount.trim() !== '')
        .map((row) => ({
          name: row.name.trim(),
          amount: Number(row.amount),
          category: row.category,
        })),
    }),
  );

  function updateLeakRow(index: number, patch: Partial<ExpenseRow>) {
    setLeakRows((previous) =>
      previous.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  }

  const [discountPreSale, setDiscountPreSale] = useState('');
  const [discountWas, setDiscountWas] = useState('');
  const [discountSale, setDiscountSale] = useState('');
  const [discountState, runDiscount] = useToolRunner(() =>
    discountValidatorTool({
      advertised_price: Number(discountSale),
      claimed_original_price: Number(discountWas),
      baseline_price: Number(discountPreSale),
    }),
  );

  return (
    <div>
      <h2 className="text-[22px] font-bold leading-snug text-[var(--text-primary)]">Tools</h2>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
        Standalone calculators. They call the backend tools endpoints; results
        show every field the backend returns.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <ToolCard
          title="Margin calculator"
          description="Gross margin, net profit, and break-even volume for a trade."
        >
          <form onSubmit={runMargin} className="mt-3 space-y-3">
            <NumberField
              id="margin-cost"
              label="Cost per unit"
              value={costPerUnit}
              onChange={setCostPerUnit}
            />
            <NumberField
              id="margin-selling"
              label="Selling price"
              value={sellingPrice}
              onChange={setSellingPrice}
            />
            <NumberField
              id="margin-quantity"
              label="Quantity"
              value={quantity}
              onChange={setQuantity}
            />
            <NumberField
              id="margin-fixed"
              label="Fixed costs (optional)"
              value={fixedCosts}
              onChange={setFixedCosts}
              required={false}
            />
            <button
              type="submit"
              disabled={marginState.loading}
              className="min-h-11 w-full rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
            >
              {marginState.loading ? 'Calculating…' : 'Calculate margin'}
            </button>
          </form>
          <ToolFooter state={marginState} />
        </ToolCard>

        <ToolCard
          title="Land converter"
          description="Marla, kanal, square feet, acres, and hectares. 1 kanal = 20 marla."
        >
          <form onSubmit={runLand} className="mt-3 space-y-3">
            <NumberField
              id="land-value"
              label="Value"
              value={landValue}
              onChange={setLandValue}
            />
            <div className="grid grid-cols-2 gap-3">
              <Field id="land-from" label="From unit">
                <select
                  id="land-from"
                  value={fromUnit}
                  onChange={(event) => setFromUnit(event.target.value)}
                  className={inputClass}
                >
                  {LAND_UNITS.map((unit) => (
                    <option key={unit} value={unit}>
                      {unit}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="land-to" label="To unit">
                <select
                  id="land-to"
                  value={toUnit}
                  onChange={(event) => setToUnit(event.target.value)}
                  className={inputClass}
                >
                  {LAND_UNITS.map((unit) => (
                    <option key={unit} value={unit}>
                      {unit}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field id="land-standard" label="Marla standard">
              <select
                id="land-standard"
                value={marlaStandard}
                onChange={(event) => setMarlaStandard(event.target.value)}
                className={inputClass}
              >
                <option value="225">225 sq ft per marla</option>
                <option value="272">272 sq ft per marla</option>
              </select>
            </Field>
            <button
              type="submit"
              disabled={landState.loading}
              className="min-h-11 w-full rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
            >
              {landState.loading ? 'Converting…' : 'Convert'}
            </button>
          </form>
          <ToolFooter state={landState} />
        </ToolCard>

        <ToolCard
          title="Installment audit"
          description="Total paid, finance charge, and APR for an installment plan versus cash."
        >
          <form onSubmit={runInstallment} className="mt-3 space-y-3">
            <NumberField
              id="installment-cash"
              label="Cash price"
              value={cashPrice}
              onChange={setCashPrice}
            />
            <NumberField
              id="installment-down"
              label="Down payment"
              value={downPayment}
              onChange={setDownPayment}
            />
            <NumberField
              id="installment-monthly"
              label="Monthly installment"
              value={monthlyInstallment}
              onChange={setMonthlyInstallment}
            />
            <NumberField
              id="installment-months"
              label="Months"
              value={months}
              onChange={setMonths}
            />
            <button
              type="submit"
              disabled={installmentState.loading}
              className="min-h-11 w-full rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
            >
              {installmentState.loading ? 'Auditing…' : 'Audit installment plan'}
            </button>
          </form>
          <ToolFooter state={installmentState} />
        </ToolCard>

        <ToolCard
          title="Brand markup"
          description="How much of the asking price is brand premium above the making cost?"
        >
          <form onSubmit={runMarkup} className="mt-3 space-y-3">
            <NumberField
              id="markup-making"
              label="Making cost"
              value={makingCost}
              onChange={setMakingCost}
            />
            <NumberField
              id="markup-asking"
              label="Asking price"
              value={askingPrice}
              onChange={setAskingPrice}
            />
            <button
              type="submit"
              disabled={markupState.loading}
              className="min-h-11 w-full rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
            >
              {markupState.loading ? 'Calculating…' : 'Calculate markup'}
            </button>
          </form>
          <ToolFooter state={markupState} />
        </ToolCard>

        <ToolCard
          title="Currency converter"
          description="Convert an amount using free Frankfurter rates from the backend. If rates are unavailable, the backend returns an error — no rate is invented."
        >
          <form onSubmit={runConvert} className="mt-3 space-y-3">
            <NumberField
              id="convert-amount"
              label="Amount"
              value={convertAmount}
              onChange={setConvertAmount}
            />
            <div className="grid grid-cols-2 gap-3">
              <Field id="convert-from" label="From currency">
                <select
                  id="convert-from"
                  value={convertFrom}
                  onChange={(event) => setConvertFrom(event.target.value)}
                  className={inputClass}
                >
                  {CURRENCIES.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="convert-to" label="To currency">
                <select
                  id="convert-to"
                  value={convertTo}
                  onChange={(event) => setConvertTo(event.target.value)}
                  className={inputClass}
                >
                  {CURRENCIES.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <button
              type="submit"
              disabled={convertState.loading}
              className="min-h-11 w-full rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
            >
              {convertState.loading ? 'Converting…' : 'Convert currency'}
            </button>
          </form>
          <ToolFooter state={convertState} />
        </ToolCard>

        <ToolCard
          title="Savings goal planner"
          description="Required monthly deposit and timeline to fund a target purchase, interest-free."
        >
          <form onSubmit={runGoal} className="mt-3 space-y-3">
            <NumberField
              id="goal-target"
              label="Target amount"
              value={goalTarget}
              onChange={setGoalTarget}
            />
            <NumberField
              id="goal-current"
              label="Current savings (optional)"
              value={goalCurrent}
              onChange={setGoalCurrent}
              required={false}
            />
            <NumberField
              id="goal-deposit"
              label="Monthly deposit you can pay (optional)"
              value={goalDeposit}
              onChange={setGoalDeposit}
              required={false}
            />
            <NumberField
              id="goal-months"
              label="Months to save (optional if deposit given)"
              value={goalMonths}
              onChange={setGoalMonths}
              required={false}
            />
            <p className="text-sm text-[var(--text-secondary)]">
              Give a monthly deposit, a number of months, or both.
            </p>
            <button
              type="submit"
              disabled={goalState.loading}
              className="min-h-11 w-full rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
            >
              {goalState.loading ? 'Planning…' : 'Plan savings goal'}
            </button>
          </form>
          <ToolFooter state={goalState} />
        </ToolCard>

        <ToolCard
          title="Expense leakage auditor"
          description="Checks recurring household spending against income and flags disproportionate discretionary spending."
        >
          <form onSubmit={runLeak} className="mt-3 space-y-3">
            <NumberField
              id="leak-income"
              label="Monthly income"
              value={leakIncome}
              onChange={setLeakIncome}
            />
            {leakRows.map((row, index) => (
              <div
                key={index}
                className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-3"
              >
                <Field id={`leak-name-${index}`} label={`Expense ${index + 1} name`}>
                  <input
                    id={`leak-name-${index}`}
                    type="text"
                    value={row.name}
                    onChange={(event) =>
                      updateLeakRow(index, { name: event.target.value })
                    }
                    placeholder="e.g. Rent, Netflix, Groceries"
                    className={inputClass}
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <NumberField
                    id={`leak-amount-${index}`}
                    label="Amount"
                    value={row.amount}
                    onChange={(value) => updateLeakRow(index, { amount: value })}
                    required={false}
                  />
                  <Field id={`leak-category-${index}`} label="Category">
                    <select
                      id={`leak-category-${index}`}
                      value={row.category}
                      onChange={(event) =>
                        updateLeakRow(index, { category: event.target.value })
                      }
                      className={inputClass}
                    >
                      {EXPENSE_CATEGORIES.map((category) => (
                        <option key={category} value={category}>
                          {category}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                {leakRows.length > 1 ? (
                  <button
                    type="button"
                    onClick={() =>
                      setLeakRows((previous) =>
                        previous.filter((_, i) => i !== index),
                      )
                    }
                    className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-card)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)]"
                  >
                    Remove expense
                  </button>
                ) : null}
              </div>
            ))}
            <button
              type="button"
              onClick={() =>
                setLeakRows((previous) => [
                  ...previous,
                  { name: '', amount: '', category: 'other' },
                ])
              }
              className="min-h-11 w-full rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-2.5 text-base font-semibold text-[var(--text-primary)]"
            >
              Add another expense
            </button>
            <p className="text-sm text-[var(--text-secondary)]">
              Housing, utilities, groceries, transport, health, and education
              count as essential; other categories count as discretionary.
              Rows left blank are ignored.
            </p>
            <button
              type="submit"
              disabled={leakState.loading}
              className="min-h-11 w-full rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
            >
              {leakState.loading ? 'Auditing…' : 'Audit expenses'}
            </button>
          </form>
          <ToolFooter state={leakState} />
        </ToolCard>

        <ToolCard
          title="Real vs fake discount validator"
          description="Compares an advertised sale price against the pre-sale price to detect an artificial markup before the sale."
        >
          <form onSubmit={runDiscount} className="mt-3 space-y-3">
            <NumberField
              id="discount-presale"
              label="Price before sale (baseline)"
              value={discountPreSale}
              onChange={setDiscountPreSale}
            />
            <NumberField
              id="discount-was"
              label="Advertised “was” price"
              value={discountWas}
              onChange={setDiscountWas}
            />
            <NumberField
              id="discount-sale"
              label="Sale price (advertised price)"
              value={discountSale}
              onChange={setDiscountSale}
            />
            <button
              type="submit"
              disabled={discountState.loading}
              className="min-h-11 w-full rounded-lg bg-emerald-500 px-4 py-2.5 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
            >
              {discountState.loading ? 'Validating…' : 'Validate discount'}
            </button>
          </form>
          <ToolFooter state={discountState} />
        </ToolCard>
      </div>
    </div>
  );
}
