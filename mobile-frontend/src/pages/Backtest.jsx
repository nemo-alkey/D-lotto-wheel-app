import { useEffect, useState } from 'react';
import { listWheels, runBacktest } from '../api/client.js';
import LoadingSpinner from '../components/LoadingSpinner.jsx';

const money = (v) => `$${Number(v).toFixed(2)}`;

export default function Backtest() {
  const [wheels, setWheels] = useState(null);
  const [wheel, setWheel] = useState('');
  const [draws, setDraws] = useState('50');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [wheelsError, setWheelsError] = useState(null);

  useEffect(() => {
    listWheels()
      .then((d) => {
        const names = Object.keys(d.wheels);
        setWheels(names);
        if (names.length > 0) setWheel(names[0]);
      })
      .catch((e) => setWheelsError(e.message || 'Failed to load wheels'));
  }, []);

  const onSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    const n = parseInt(draws, 10);
    if (Number.isNaN(n) || n < 1) {
      setError('Enter a positive number of recent draws.');
      return;
    }
    setLoading(true);
    try {
      const data = await runBacktest(wheel, n);
      if (data.error) {
        setError(data.error);
      } else {
        setResult(data);
      }
    } catch (err) {
      setError(err.message || 'Backtest failed');
    } finally {
      setLoading(false);
    }
  };

  if (wheelsError) {
    return (
      <div className="rounded-xl border border-rose-800 bg-rose-950/50 p-4 text-sm text-rose-200">{wheelsError}</div>
    );
  }
  if (!wheels) return <LoadingSpinner label="Loading wheels..." />;

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="text-lg font-semibold">Bonus Impact Backtest</h2>

        <div>
          <label className="mb-1 block text-sm text-neutral-400">Wheel</label>
          <select
            value={wheel}
            onChange={(e) => setWheel(e.target.value)}
            className="min-h-[44px] w-full rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm"
          >
            {wheels.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="mb-1 block text-sm text-neutral-400">Number of recent draws</label>
          <input
            type="number"
            min="1"
            value={draws}
            onChange={(e) => setDraws(e.target.value)}
            className="min-h-[44px] w-32 rounded-lg border border-neutral-700 bg-neutral-800 px-3 text-sm"
          />
        </div>

        {error && (
          <div className="rounded-lg border border-rose-800 bg-rose-950/50 p-3 text-sm text-rose-200">{error}</div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="min-h-[44px] w-full rounded-lg bg-emerald-600 px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          {loading ? 'Running...' : 'Run Backtest'}
        </button>
      </form>

      {loading && <LoadingSpinner label="Running backtest..." />}

      {result && (
        <div className="space-y-4 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
          <h3 className="text-lg font-semibold">Summary</h3>
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <Stat label="Draws Tested" value={result.draws_tested} />
            <Stat label="Prize With Bonus" value={money(result.total_prize_with_bonus)} />
            <Stat label="Prize Without Bonus" value={money(result.total_prize_without_bonus)} />
            <Stat label="Bonus Premium" value={`${result.bonus_premium_percent}%`} />
            <Stat label="Upgraded Tickets" value={result.upgraded_tickets} />
            <Stat label="Bonus Added Value" value={money(result.bonus_added_value)} />
          </div>
          {result.upgrade_breakdown && Object.keys(result.upgrade_breakdown).length > 0 && (
            <div>
              <p className="mb-1 text-sm text-neutral-400">Upgrade breakdown</p>
              <ul className="text-sm">
                {Object.entries(result.upgrade_breakdown).map(([k, v]) => (
                  <li key={k} className="flex justify-between border-b border-neutral-800/50 py-1">
                    <span>{k}</span>
                    <span>{v}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-neutral-800/60 p-3">
      <p className="text-xs text-neutral-400">{label}</p>
      <p className="mt-0.5 font-semibold">{value}</p>
    </div>
  );
}
