import { useEffect, useState } from 'react';
import { getWheel, listWheels } from '../api/client.js';
import LoadingSpinner from '../components/LoadingSpinner.jsx';
import TicketCard from '../components/TicketCard.jsx';

export default function Wheels() {
  const [wheels, setWheels] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);

  useEffect(() => {
    listWheels()
      .then((d) => setWheels(Object.values(d.wheels)))
      .catch((e) => setError(e.message || 'Failed to load wheels'));
  }, []);

  const openWheel = async (name) => {
    setSelected(name);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const d = await getWheel(name);
      setDetail(d);
    } catch (e) {
      setDetailError(e.message || 'Failed to load wheel');
    } finally {
      setDetailLoading(false);
    }
  };

  if (error) {
    return (
      <div className="rounded-xl border border-rose-800 bg-rose-950/50 p-4 text-sm text-rose-200">{error}</div>
    );
  }
  if (!wheels) return <LoadingSpinner label="Loading wheels..." />;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {wheels.map((w) => (
          <button
            key={w.name}
            onClick={() => openWheel(w.name)}
            className={`min-h-[44px] rounded-xl border p-4 text-left transition-colors ${
              selected === w.name
                ? 'border-emerald-500 bg-emerald-950/30'
                : 'border-neutral-800 bg-neutral-900 hover:border-neutral-600'
            }`}
          >
            <p className="font-semibold">{w.name}</p>
            <p className="mt-1 text-sm text-neutral-400">
              {w.tickets} tickets · pool of {w.pool_size}
            </p>
            <p className="text-sm text-neutral-400">Suggested powerball: {w.suggested_powerball}</p>
          </button>
        ))}
      </div>

      {selected && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">{selected} tickets</h2>
          {detailLoading && <LoadingSpinner label="Loading tickets..." />}
          {detailError && (
            <div className="rounded-xl border border-rose-800 bg-rose-950/50 p-4 text-sm text-rose-200">
              {detailError}
            </div>
          )}
          {detail && (
            <>
              <p className="mb-3 text-sm text-neutral-400">
                {detail.ticket_count} tickets · cost ${Number(detail.cost).toFixed(2)} · suggested powerball{' '}
                {detail.suggested_powerball}
              </p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {detail.tickets.map((t, i) => (
                  <TicketCard key={i} numbers={t} footer={`Ticket ${i + 1}`} />
                ))}
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
