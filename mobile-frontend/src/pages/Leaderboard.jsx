import { useEffect, useState } from 'react';
import { getLeaderboard } from '../api/client.js';
import LoadingSpinner from '../components/LoadingSpinner.jsx';

const pct = (v) => `${(v * 100).toFixed(1)}%`;

export default function Leaderboard() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getLeaderboard()
      .then((d) => setRows(d.leaderboard || []))
      .catch((e) => setError(e.message || 'Failed to load leaderboard'));
  }, []);

  if (error) {
    return (
      <div className="rounded-xl border border-rose-800 bg-rose-950/50 p-4 text-sm text-rose-200">{error}</div>
    );
  }
  if (!rows) return <LoadingSpinner label="Loading leaderboard..." />;

  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-neutral-800 bg-neutral-900 p-8 text-center text-neutral-400">
        No predictors evaluated yet.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {rows.map((r) => (
        <div key={r.rank} className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
          <div className="flex items-center justify-between">
            <p className="font-semibold">
              <span className="mr-2 text-emerald-400">#{r.rank}</span>
              {r.predictor_name}
            </p>
            <span className="text-xs text-neutral-500">window {r.window_size}</span>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-sm">
            <Stat label="Hit Rate" value={pct(r.hit_rate)} />
            <Stat label="Brier Score" value={r.brier_score.toFixed(4)} />
            <Stat label="Draws Evaluated" value={r.draws_evaluated} />
          </div>
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-neutral-800/60 p-2">
      <p className="text-xs text-neutral-400">{label}</p>
      <p className="mt-0.5 font-medium">{value}</p>
    </div>
  );
}
