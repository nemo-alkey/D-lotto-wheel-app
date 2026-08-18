import NumberBall from './NumberBall.jsx';

export default function TicketCard({ numbers, matched = [], footer }) {
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900 p-3">
      <div className="flex flex-wrap items-center justify-center gap-2">
        {numbers.map((n) => (
          <NumberBall key={n} number={n} size="sm" highlighted={matched.includes(n)} />
        ))}
      </div>
      {footer && <p className="mt-2 text-center text-xs text-neutral-400">{footer}</p>}
    </div>
  );
}
