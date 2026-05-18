import { useEffect, useState, useMemo } from 'react'
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Label,
} from 'recharts'
import { fetchPlayers } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'

const ROLE_OPTIONS = [
  { value: '', label: 'All Players' },
  { value: 'star', label: 'Stars (15+ PPG)' },
  { value: 'role', label: 'Role Players (8-15 PPG)' },
  { value: 'bench', label: 'Bench (<8 PPG)' },
]

const POS_COLOR = {
  guard: '#3b82f6',
  forward: '#22c55e',
  center: '#f97316',
}

const ScatterDot = (props) => {
  const { cx, cy, payload } = props
  if (!cx || !cy) return null
  const r = Math.max(8, Math.min(22, 8 + (payload.avg_pts / 40) * 14))
  const color = POS_COLOR[payload.position] || '#94a3b8'
  const clipId = `c-${payload.player_id}`
  return (
    <g>
      <defs>
        <clipPath id={clipId}>
          <circle cx={cx} cy={cy} r={r} />
        </clipPath>
      </defs>
      {payload.headshot_url && (
        <image
          x={cx - r}
          y={cy - r}
          width={r * 2}
          height={r * 1.6}
          href={payload.headshot_url}
          clipPath={`url(#${clipId})`}
          preserveAspectRatio="xMidYMin slice"
        />
      )}
      <circle cx={cx} cy={cy} r={r} fill={payload.headshot_url ? 'none' : color + '44'} stroke={color} strokeWidth={2} />
    </g>
  )
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const p = payload[0]?.payload
  if (!p) return null
  return (
    <div
      className="rounded-lg px-3 py-2 text-sm"
      style={{ background: '#1a2230', border: '1px solid rgba(255,255,255,0.12)', color: '#f1f5f9', pointerEvents: 'none' }}
    >
      <p className="font-bold">{p.player_name}</p>
      <p style={{ color: '#94a3b8' }}>{p.team} · {p.position}</p>
      <p>EHI: <span style={{ color: '#f97316', fontWeight: 700 }}>{p.avg_EHI?.toFixed(1)}</span></p>
      <p>PPG: <span style={{ color: '#fbbf24' }}>{p.avg_pts?.toFixed(1)}</span></p>
      <p>SSS: <span style={{ color: '#06b6d4' }}>{p.avg_SSS?.toFixed(1)}</span></p>
      <p>FDS: <span style={{ color: '#a855f7' }}>{p.avg_FDS?.toFixed(1)}</span></p>
    </div>
  )
}

export default function ScatterPlot({ season }) {
  const [players, setPlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [role, setRole] = useState('')

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchPlayers(season, { min_games: 20 })
      .then(data => setPlayers(data.players || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [season])

  const filtered = useMemo(() => {
    if (!role) return players
    if (role === 'star') return players.filter(p => p.avg_pts >= 15)
    if (role === 'role') return players.filter(p => p.avg_pts >= 8 && p.avg_pts < 15)
    if (role === 'bench') return players.filter(p => p.avg_pts < 8)
    return players
  }, [players, role])

  if (loading) return <LoadingSpinner text="Loading scatter data..." />
  if (error) return (
    <div className="rounded-xl p-6 text-center" style={{ background: '#131920', border: '1px solid rgba(239,68,68,0.3)' }}>
      <p className="text-red-400 font-medium">Failed to load data</p>
      <p className="text-sm mt-1" style={{ color: '#64748b' }}>{error}</p>
    </div>
  )

  return (
    <div className="flex flex-col gap-4 max-w-6xl mx-auto">
      {/* Header + controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold" style={{ color: '#f1f5f9' }}>Scoring Skill vs. Foul Drawing Legitimacy</h2>
          <p className="text-sm mt-0.5" style={{ color: '#64748b' }}>
            Players with 20+ games played · Min games = 20
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {ROLE_OPTIONS.map(o => (
            <button
              key={o.value}
              onClick={() => setRole(o.value)}
              className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
              style={{
                background: role === o.value ? '#f97316' : '#1a2230',
                color: role === o.value ? '#fff' : '#94a3b8',
                border: '1px solid ' + (role === o.value ? '#f97316' : 'rgba(255,255,255,0.10)'),
              }}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <p className="text-sm" style={{ color: '#94a3b8' }}>
        Players in the top-right corner score skillfully AND draw fouls legitimately — the ideal ethical scorer.
      </p>
      <div
        className="rounded-xl p-4 pt-6"
        style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <ResponsiveContainer width="100%" height={500}>
          <ScatterChart margin={{ top: 10, right: 30, bottom: 40, left: 30 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="avg_SSS"
              type="number"
              domain={['auto', 'auto']}
              tick={{ fill: '#64748b', fontSize: 11 }}
              tickLine={{ stroke: 'rgba(255,255,255,0.1)' }}
              axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
            >
              <Label value="SSS — Scoring Skill Score (self-created offense + playmaking)" position="bottom" offset={20} fill="#64748b" fontSize={12} />
            </XAxis>
            <YAxis
              dataKey="avg_FDS"
              type="number"
              domain={['auto', 'auto']}
              tick={{ fill: '#64748b', fontSize: 11 }}
              tickLine={{ stroke: 'rgba(255,255,255,0.1)' }}
              axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
            >
              <Label value="FDS — Foul Drawing Legitimacy (how earned were the free throws?)" angle={-90} position="insideLeft" offset={-10} fill="#64748b" fontSize={12} />
            </YAxis>
            <Tooltip content={<CustomTooltip />} cursor={false} />
            <Scatter
              data={filtered}
              shape={<ScatterDot />}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div
        className="rounded-xl p-4 flex flex-wrap gap-6 items-center"
        style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <span className="text-xs font-medium" style={{ color: '#64748b' }}>Position:</span>
        {[
          { pos: 'Guard', color: '#3b82f6' },
          { pos: 'Forward', color: '#22c55e' },
          { pos: 'Center', color: '#f97316' },
        ].map(({ pos, color }) => (
          <div key={pos} className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full" style={{ background: color }} />
            <span className="text-xs" style={{ color: '#94a3b8' }}>{pos}</span>
          </div>
        ))}
        <span className="text-xs ml-4" style={{ color: '#64748b' }}>
          Bubble size = PPG
        </span>
        <span className="text-xs ml-auto" style={{ color: '#64748b' }}>
          {filtered.length} players shown
        </span>
      </div>
    </div>
  )
}
