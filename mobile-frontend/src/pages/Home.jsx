import { useEffect, useState } from 'react';
import { getEnsemble } from '../api/client.js';
import NumberBall from '../components/NumberBall.jsx';
import LoadingSpinner from '../components/LoadingSpinner.jsx';

export default function Home() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getEnsemble(20)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message || 'Failed to load predictions'))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <LoadingSpinner label="Loading ensemble predictions..." />;

  if (error) {
    return (
      <div className="rounded-xl border border-rose-800 bg-rose-950/50 p-4 text-sm text-rose-200">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section>
        <h2 className="mb-3 text-lg font-semibold">Top {data.main.length} Main Numbers</h2>
        <div className="grid grid-cols-5 gap-y-3 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
          {data.main.map(([num, prob]) => (
            <NumberBall key={num} number={num} probability={prob} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Top Bonus Numbers</h2>
        <div className="flex flex-wrap gap-2 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
          {data.bonus.map(([num, prob]) => (
            <NumberBall key={num} number={num} size="lg" probability={prob} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Top Powerball Picks</h2>
        <div className="flex flex-wrap gap-2 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
          {data.powerball.map(([num, prob]) => (
            <NumberBall key={num} number={num} size="lg" probability={prob} />
          ))}
        </div>
      </section>

      {data.ensemble_weights && (
        <p className="text-xs text-neutral-500">
          Ensemble weights:{' '}
          {Object.entries(data.ensemble_weights)
            .map(([k, v]) => `${k} ${(v * 100).toFixed(0)}%`)
            .join(' · ')}
        </p>
      )}
    </div>
  );
}
