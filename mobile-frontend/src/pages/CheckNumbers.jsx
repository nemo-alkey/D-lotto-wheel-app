import { useEffect, useState } from 'react';
import { checkNumbers, listWheels } from '../api/client.js';
import LoadingSpinner from '../components/LoadingSpinner.jsx';

const money = (v) => `$${Number(v).toFixed(2)}`;

export default function CheckNumbers() {
  const [wheels, setWheels] = useState(null);
  const [wheel, setWheel] = useState('');
  const [numbers, setNumbers] = useState(['', '', '', '', '', '']);
  const [powerball, setPowerball] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    listWheels()
      .then((d) => {
        const names = Object.keys(d.wheels);
        setWheels(names);
        if (names.length > 0) setWheel(names[0]);
      })
      .catch((e) => setError(e.message || 'Failed to load wheels'));
  }, []);

  const setNumberAt = (i, value) => {
    const next = [...numbers];
    next[i] = value;
    setNumbers(next);
  };

  const validate = () => {
    const parsed = numbers.map((s) => parseInt(s, 10));
    if (parsed.some((n) => Number.isNaN(n) || n < 1 || n > 40)) {
      return 'All 6 numbers must be between 1 and 40.';
    }
    if (new Set(parsed).size !== 6) {
      return 'All 6 numbers must be unique.';
    }
    const pb = parseInt(powerball, 10);
    if (Number.isNaN(pb) || pb < 1 || pb > 10) {
      return 'Powerball must be between 1 and 10.';
    }
    return null;
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setSubmitting(true);
    try {
      const draw = numbers.map((s) => parseInt(s, 10)).sort((a, b) => a - b);
      const data = await checkNumbers(wheel, draw, parseInt(powerball, 10));
      setResult(data);
    } catch (err) {
      setError(err.message || 'Check failed');
    } finally {
      setSubmitting(false);
    }
  };

  if (!wheels) {
    return error ? (
      <div className="rounded-xl border border-rose-800 bg-rose-950/50 p-4 text-sm text-rose-200">{error}</div>
    ) : (
      <LoadingSpinner label="Loading wheels..." />
    );
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="text-lg font-semibold">Check Draw Against a Wheel</h2>

        <div>
          <label className="mb-1 block text-sm text-neutral-400">Wheel</label>
          <select
            value={wheel}
            onChange={(e) => setWheel(e.target.value)}
            className="w-full rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm"
          >
            {wheels.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm text-neutral-400">Drawn numbers (1-40, unique)</label>
          <div className="grid grid-cols-6 gap-2">
            {numbers.map((v, i) => (
              <input
                key={i}
                type="number"
                min="1"
                max="40"
                required
                value={v}
                onChange={(e) => setNumberAt(i, e.target.value)}
                className="min-h-[44px] w-full rounded-lg border border-neutral-700 bg-neutral-800 px-2 text-center text-sm"
              />
            ))}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-sm text-neutral-400">Powerball (1-10)</label>
          <input
            type="number"
            min="1"
            max="10"
            required
            value={powerball}
            onChange={(e) => setPowerball(e.target.value)}
            className="min-h-[44px] w-24 rounded-lg border border-neutral-700 bg-neutral-800 px-3 text-sm"
          />
        </div>

        {error && (
          <div className="rounded-lg border border-rose-800 bg-rose-950/50 p-3 text-sm text-rose-200">{error}</div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="min-h-[44px] w-full rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          {submitting ? 'Checking...' : 'Check Numbers'}
        </button>
      </form>

      {result && (
        <div className="space-y-4 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
          <h3 className="text-lg font-semibold">Results</h3>
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <Stat label="Tickets" value={result.ticket_count} />
            <Stat label="Cost" value={money(result.cost)} />
            <Stat label="Total Prize" value={money(result.total_prize)} />
            <Stat label="Net" value={money(result.net)} highlight={result.net >= 0} />
            <Stat label="ROI" value={`${result.roi_pct}%`} highlight={result.roi_pct >= 0} />
            <Stat label="Pool Overlap" value={`${result.pool_overlap}/6`} />
          </div>

          {result.divisions.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-neutral-800 text-neutral-400">
                    <th className="py-2 pr-3">Division</th>
                    <th className="py-2 pr-3">Winners</th>
                    <th className="py-2 pr-3">Per Ticket</th>
                    <th className="py-2">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {result.divisions.map((d) => (
                    <tr key={d.division} className="border-b border-neutral-800/50">
                      <td className="py-2 pr-3">Div {d.division}</td>
                      <td className="py-2 pr-3">{d.winners}</td>
                      <td className="py-2 pr-3">{money(d.prize_per_ticket)}</td>
                      <td className="py-2">{money(d.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-neutral-400">No division prizes hit for this draw.</p>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <div className="rounded-lg bg-neutral-800/60 p-3">
      <p className="text-xs text-neutral-400">{label}</p>
      <p className={`mt-0.5 font-semibold ${highlight == null ? '' : highlight ? 'text-emerald-400' : 'text-rose-400'}`}>
        {value}
      </p>
    </div>
  );
}
