export default function LoadingSpinner({ label }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-neutral-700 border-t-emerald-400" />
      {label && <p className="text-sm text-neutral-400">{label}</p>}
    </div>
  );
}
