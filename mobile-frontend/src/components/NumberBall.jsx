const BLOCK_COLORS = [
  'bg-amber-500 text-neutral-950',    // 1-8
  'bg-emerald-500 text-neutral-950',  // 9-16
  'bg-sky-500 text-neutral-950',      // 17-24
  'bg-violet-500 text-white',         // 25-32
  'bg-rose-500 text-white',           // 33-40
];

const SIZES = {
  sm: 'h-7 w-7 text-xs',
  md: 'h-9 w-9 text-sm',
  lg: 'h-12 w-12 text-base',
};

export default function NumberBall({ number, size = 'md', highlighted = false, probability }) {
  const block = Math.min(Math.max(Math.ceil(number / 8), 1), 5);
  const color = BLOCK_COLORS[block - 1];
  return (
    <div className="flex flex-col items-center gap-0.5">
      <div
        className={`flex items-center justify-center rounded-full font-semibold ${color} ${SIZES[size]} ${
          highlighted ? 'ring-2 ring-yellow-300 ring-offset-2 ring-offset-neutral-950' : ''
        }`}
      >
        {number}
      </div>
      {probability != null && (
        <span className="text-[10px] text-neutral-400">{(probability * 100).toFixed(1)}%</span>
      )}
    </div>
  );
}
