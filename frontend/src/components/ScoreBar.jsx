export default function ScoreBar({ value, max = 100, color = '#f97316' }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div className="flex items-center gap-1">
      <div className="w-12 h-1.5 bg-white/10 rounded-full overflow-hidden">
        <div
          style={{ width: `${pct}%`, background: color }}
          className="h-full rounded-full"
        />
      </div>
      <span className="text-xs text-slate-300 w-9 text-right">
        {value?.toFixed(1)}
      </span>
    </div>
  )
}
