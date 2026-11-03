import { useState } from 'react';
import type { FormEvent } from 'react';
import type { AnalyzeRequest, Category, Currency } from '../lib/api';
import BarcodeLookup from './BarcodeLookup';
import ImageUpload from './ImageUpload';

const CURRENCIES: Currency[] = ['PKR', 'USD', 'INR', 'GBP', 'EUR', 'AED'];

const CATEGORIES: { value: Category; label: string }[] = [
  { value: 'retail', label: 'Retail product' },
  { value: 'vehicle', label: 'Vehicle' },
  { value: 'property', label: 'Property / land' },
  { value: 'perishable', label: 'Perishable commodity' },
  { value: 'inventory', label: 'Inventory / stock' },
];

interface ExampleChip {
  label: string;
  description: string;
  askingPrice: string;
  quantity: string;
  unit: string;
  category: Category;
  sellerNotes: string;
  daysToSell: string;
  areaMarla: string;
  marlaStandard: '225' | '272';
}

const EXAMPLES: ExampleChip[] = [
  {
    label: '30 kg tomatoes wholesale at 80 PKR/kg',
    description:
      'Buying 30 kg tomatoes in wholesale mandi at 80 PKR/kg to resell over the next 5 days in Bahawalpur.',
    askingPrice: '2400',
    quantity: '30',
    unit: 'kg',
    category: 'perishable',
    sellerNotes: '',
    daysToSell: '5',
    areaMarla: '',
    marlaStandard: '225',
  },
  {
    label: '2018 Suzuki Alto VXR, 88,000 km, 1,920,000 PKR',
    description: '2018 Suzuki Alto VXR, 88,000 km, asking 1,920,000 PKR.',
    askingPrice: '1920000',
    quantity: '1',
    unit: 'car',
    category: 'vehicle',
    sellerNotes: 'Seller says price is firm. No mention of token tax or accident history.',
    daysToSell: '',
    areaMarla: '',
    marlaStandard: '225',
  },
  {
    label: '5 Marla plot file, 1,500,000 PKR, no NOC mentioned',
    description:
      '5 Marla residential plot file in a new private housing scheme near Bahawalpur bypass, 1,500,000 PKR on installment.',
    askingPrice: '1500000',
    quantity: '1',
    unit: 'plot',
    category: 'property',
    sellerNotes: 'Agent says NOC is in process. No approved layout plan shown.',
    daysToSell: '',
    areaMarla: '5',
    marlaStandard: '225',
  },
];

interface DecisionFormProps {
  submitting: boolean;
  onSubmit: (payload: AnalyzeRequest) => void;
  onCancel: () => void;
}

const inputClass =
  'min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] px-3 py-2 text-base text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-colors duration-150 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/50 focus:outline-none disabled:opacity-50';

const labelClass = 'mb-1 block text-sm font-semibold text-[var(--text-primary)]';

export default function DecisionForm({
  submitting,
  onSubmit,
  onCancel,
}: DecisionFormProps) {
  const [description, setDescription] = useState('');
  const [askingPrice, setAskingPrice] = useState('');
  const [currency, setCurrency] = useState<Currency>('PKR');
  const [country, setCountry] = useState('Pakistan');
  const [province, setProvince] = useState('Punjab');
  const [city, setCity] = useState('Bahawalpur');
  const [quantity, setQuantity] = useState('1');
  const [unit, setUnit] = useState('');
  const [category, setCategory] = useState<Category>('retail');
  const [sellerNotes, setSellerNotes] = useState('');
  const [daysToSell, setDaysToSell] = useState('');
  const [temperatureC, setTemperatureC] = useState('');
  const [transitDamagePct, setTransitDamagePct] = useState('');
  const [areaMarla, setAreaMarla] = useState('');
  const [marlaStandard, setMarlaStandard] = useState<'225' | '272'>('225');
  const [privateMode, setPrivateMode] = useState(false);

  function applyExample(example: ExampleChip) {
    setDescription(example.description);
    setAskingPrice(example.askingPrice);
    setQuantity(example.quantity);
    setUnit(example.unit);
    setCategory(example.category);
    setSellerNotes(example.sellerNotes);
    setDaysToSell(example.daysToSell);
    setAreaMarla(example.areaMarla);
    setMarlaStandard(example.marlaStandard);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const price = Number(askingPrice);
    const qty = Number(quantity);
    if (!description.trim() || !Number.isFinite(price) || !Number.isFinite(qty)) {
      return;
    }
    const payload: AnalyzeRequest = {
      description: description.trim(),
      asking_price: price,
      currency,
      country: country.trim() || 'Pakistan',
      province: province.trim() || 'Punjab',
      city: city.trim() || 'Bahawalpur',
      quantity: qty,
      unit: unit.trim() || 'unit',
      category,
      private_mode: privateMode,
    };
    const notes = sellerNotes.trim();
    if (notes) payload.seller_notes = notes;
    if (category === 'perishable' || category === 'inventory') {
      // Transit damage is entered as a percent (0–90); the backend
      // takes the fraction (0–0.9). Blank means the 10% default.
      const damagePct = Number(transitDamagePct);
      if (transitDamagePct.trim() !== '' && Number.isFinite(damagePct)) {
        payload.transit_damage_percent = damagePct / 100;
      }
    }
    if (category === 'perishable') {
      const days = Number(daysToSell);
      if (daysToSell.trim() !== '' && Number.isFinite(days)) {
        payload.days_to_sell = days;
      }
      const temp = Number(temperatureC);
      if (temperatureC.trim() !== '' && Number.isFinite(temp)) {
        payload.temperature_c = temp;
      }
    }
    if (category === 'property') {
      const area = Number(areaMarla);
      if (areaMarla.trim() !== '' && Number.isFinite(area)) {
        payload.area_marla = area;
      }
      payload.marla_standard = marlaStandard;
    }
    onSubmit(payload);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl border border-[var(--border)] bg-[var(--surface-card)] p-4"
    >
      <h2 className="text-[22px] font-bold leading-snug text-[var(--text-primary)]">
        What are you thinking of buying?
      </h2>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
        Describe the deal in plain words. You get one verdict, with numbers —
        not an essay.
      </p>

      <div className="mt-4 flex flex-wrap gap-2" aria-label="Example deals">
        {EXAMPLES.map((example) => (
          <button
            key={example.label}
            type="button"
            disabled={submitting}
            onClick={() => applyExample(example)}
            className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-3 py-2 text-left text-sm text-[var(--text-primary)] transition-colors duration-150 hover:border-emerald-500 disabled:opacity-50"
          >
            {example.label}
          </button>
        ))}
      </div>

      <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--surface-inset)] p-4">
        <h3 className="text-[11px] font-bold tracking-wide text-[var(--text-muted)] uppercase">
          Optional: find the product first
        </h3>
        <BarcodeLookup
          disabled={submitting}
          descriptionEmpty={description.trim() === ''}
          onFillDescription={setDescription}
        />
        <ImageUpload
          disabled={submitting}
          descriptionEmpty={description.trim() === ''}
          onFillDescription={setDescription}
        />
        <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          Anything filled in above lands in the description for you to edit
          and confirm before checking.
        </p>
      </div>

      <div className="mt-4">
        <label className={labelClass} htmlFor="description">
          Item description
        </label>
        <textarea
          id="description"
          required
          rows={4}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          disabled={submitting}
          placeholder="e.g. 30 kg tomatoes wholesale at 80 PKR/kg, to resell over 5 days"
          className={`${inputClass} resize-y`}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="asking-price">
            Asking price
          </label>
          <input
            id="asking-price"
            type="number"
            required
            min="0"
            step="any"
            inputMode="decimal"
            value={askingPrice}
            onChange={(event) => setAskingPrice(event.target.value)}
            disabled={submitting}
            placeholder="2400"
            className={`${inputClass} font-mono`}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="currency">
            Currency
          </label>
          <select
            id="currency"
            value={currency}
            onChange={(event) => setCurrency(event.target.value as Currency)}
            disabled={submitting}
            className={inputClass}
          >
            {CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div>
          <label className={labelClass} htmlFor="country">
            Country
          </label>
          <input
            id="country"
            type="text"
            value={country}
            onChange={(event) => setCountry(event.target.value)}
            disabled={submitting}
            className={inputClass}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="province">
            Province / state
          </label>
          <input
            id="province"
            type="text"
            value={province}
            onChange={(event) => setProvince(event.target.value)}
            disabled={submitting}
            className={inputClass}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="city">
            City
          </label>
          <input
            id="city"
            type="text"
            value={city}
            onChange={(event) => setCity(event.target.value)}
            disabled={submitting}
            className={inputClass}
          />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div>
          <label className={labelClass} htmlFor="quantity">
            Quantity
          </label>
          <input
            id="quantity"
            type="number"
            required
            min="0"
            step="any"
            inputMode="decimal"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            disabled={submitting}
            className={`${inputClass} font-mono`}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="unit">
            Unit
          </label>
          <input
            id="unit"
            type="text"
            value={unit}
            onChange={(event) => setUnit(event.target.value)}
            disabled={submitting}
            placeholder="kg, car, plot…"
            className={inputClass}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="category">
            Category
          </label>
          <select
            id="category"
            value={category}
            onChange={(event) => setCategory(event.target.value as Category)}
            disabled={submitting}
            className={inputClass}
          >
            {CATEGORIES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {category === 'perishable' ? (
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className={labelClass} htmlFor="days-to-sell">
              Days to sell
            </label>
            <input
              id="days-to-sell"
              type="number"
              min="0"
              step="any"
              inputMode="decimal"
              value={daysToSell}
              onChange={(event) => setDaysToSell(event.target.value)}
              disabled={submitting}
              placeholder="5"
              className={`${inputClass} font-mono`}
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="temperature">
              Temperature (°C, optional)
            </label>
            <input
              id="temperature"
              type="number"
              step="any"
              inputMode="decimal"
              value={temperatureC}
              onChange={(event) => setTemperatureC(event.target.value)}
              disabled={submitting}
              placeholder="35"
              className={`${inputClass} font-mono`}
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="transit-damage">
              Transit damage (%, optional)
            </label>
            <input
              id="transit-damage"
              type="number"
              min="0"
              max="90"
              step="any"
              inputMode="decimal"
              value={transitDamagePct}
              onChange={(event) => setTransitDamagePct(event.target.value)}
              disabled={submitting}
              placeholder="10"
              className={`${inputClass} font-mono`}
            />
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              Blank = default 10%.
            </p>
          </div>
        </div>
      ) : null}

      {category === 'inventory' ? (
        <div className="mt-4">
          <label className={labelClass} htmlFor="transit-damage-inventory">
            Transit damage (%, optional)
          </label>
          <input
            id="transit-damage-inventory"
            type="number"
            min="0"
            max="90"
            step="any"
            inputMode="decimal"
            value={transitDamagePct}
            onChange={(event) => setTransitDamagePct(event.target.value)}
            disabled={submitting}
            placeholder="10"
            className={`${inputClass} font-mono`}
          />
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Blank = default 10%.
          </p>
        </div>
      ) : null}

      {category === 'property' ? (
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass} htmlFor="area-marla">
              Area in Marla
            </label>
            <input
              id="area-marla"
              type="number"
              min="0"
              step="any"
              inputMode="decimal"
              value={areaMarla}
              onChange={(event) => setAreaMarla(event.target.value)}
              disabled={submitting}
              placeholder="5"
              className={`${inputClass} font-mono`}
            />
          </div>
          <div>
            <fieldset>
              <legend className={labelClass}>Marla standard</legend>
              <div className="flex min-h-11 items-center gap-4">
                <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-[var(--text-primary)]">
                  <input
                    type="radio"
                    name="marla-standard"
                    value="225"
                    checked={marlaStandard === '225'}
                    onChange={() => setMarlaStandard('225')}
                    disabled={submitting}
                    className="h-5 w-5 accent-emerald-500"
                  />
                  <span className="font-mono">225 sq ft</span>
                </label>
                <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-[var(--text-primary)]">
                  <input
                    type="radio"
                    name="marla-standard"
                    value="272"
                    checked={marlaStandard === '272'}
                    onChange={() => setMarlaStandard('272')}
                    disabled={submitting}
                    className="h-5 w-5 accent-emerald-500"
                  />
                  <span className="font-mono">272 sq ft</span>
                </label>
              </div>
            </fieldset>
          </div>
        </div>
      ) : null}

      <div className="mt-4">
        <label className={labelClass} htmlFor="seller-notes">
          Seller claims / listing text — paste here
        </label>
        <textarea
          id="seller-notes"
          rows={3}
          value={sellerNotes}
          onChange={(event) => setSellerNotes(event.target.value)}
          disabled={submitting}
          placeholder="Paste the listing or the seller's message, exactly as written."
          className={`${inputClass} resize-y`}
        />
      </div>

      <label className="mt-4 flex min-h-11 cursor-pointer items-center gap-3 text-sm text-[var(--text-primary)]">
        <input
          type="checkbox"
          checked={privateMode}
          onChange={(event) => setPrivateMode(event.target.checked)}
          disabled={submitting}
          className="h-5 w-5 shrink-0 accent-emerald-500"
        />
        <span>
          Private check — do not save to history
          <span className="block text-sm font-normal text-[var(--text-secondary)]">
            Runs in memory only; nothing is written to history.
          </span>
        </span>
      </label>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <button
          type="submit"
          disabled={submitting}
          className="min-h-11 flex-1 rounded-lg bg-emerald-500 px-4 py-3 text-base font-bold text-stone-950 transition-colors duration-150 hover:bg-emerald-600 disabled:opacity-50"
        >
          {submitting ? 'Checking…' : 'Check This Buy →'}
        </button>
        {submitting ? (
          <button
            type="button"
            onClick={onCancel}
            className="min-h-11 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-inset)] px-4 py-3 text-base font-semibold text-[var(--text-primary)] transition-colors duration-150 hover:border-[var(--border-strong)]"
          >
            Cancel Check
          </button>
        ) : null}
      </div>
    </form>
  );
}
