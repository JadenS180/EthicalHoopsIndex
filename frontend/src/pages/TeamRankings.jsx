import { useEffect, useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { fetchTeams, fetchPlayers } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import PlayerHeadshot from '../components/PlayerHeadshot'

const POS_MAP = { center: 'C', forward: 'F', guard: 'G' }

function lerp(a, b, t) {
  return a + (b - a) * t
}

function ehi_to_color(ehi, min = 44, max = 58) {
  const t = Math.max(0, Math.min(1, (ehi - min) / (max - min)))
  // red (low) → amber (mid) → gold/green (high)
  if (t < 0.5) {
    const r = Math.round(lerp(220, 251, t * 2))
    const g = Math.round(lerp(38, 191, t * 2))
    const b = Math.round(lerp(38, 36, t * 2))
    return `rgb(${r},${g},${b})`
  } else {
    const r = Math.round(lerp(251, 34, (t - 0.5) * 2))
    const g = Math.round(lerp(191, 197, (t - 0.5) * 2))
    const b = Math.round(lerp(36, 94, (t - 0.5) * 2))
    return `rgb(${r},${g},${b})`
  }
}

const CustomBarTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return (
    <div
      className="rounded-lg px-3 py-2 text-sm"
      style={{ background: '#1a2230', border: '1px solid rgba(255,255,255,0.12)', color: '#f1f5f9' }}
    >
      <p className="font-bold">{d.team}</p>
      <p>Avg EHI: <span style={{ color: '#f97316', fontWeight: 700 }}>{d.avg_EHI?.toFixed(2)}</span></p>
      <p style={{ color: '#64748b' }}>{d.gp} games played</p>
    </div>
  )
}

export default function TeamRankings({ season }) {
  const [teams, setTeams] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [selectedTeam, setSelectedTeam] = useState(null)
  const [teamPlayers, setTeamPlayers] = useState([])
  const [loadingPlayers, setLoadingPlayers] = useState(false)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setSelectedTeam(null)
    setTeamPlayers([])
    fetchTeams(season)
      .then(data => setTeams(data.teams || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [season])

  const handleTeamClick = (team) => {
    setSelectedTeam(team.team)
    setLoadingPlayers(true)
    setTeamPlayers([])
    fetchPlayers(season, { team: team.team, min_games: 1 })
      .then(data => {
        const sorted = (data.players || []).sort((a, b) => (b.avg_EHI || 0) - (a.avg_EHI || 0))
        setTeamPlayers(sorted)
      })
      .catch(() => setTeamPlayers([]))
      .finally(() => setLoadingPlayers(false))
  }

  if (loading) return <LoadingSpinner text="Loading team rankings..." />
  if (error) return (
    <div className="rounded-xl p-6 text-center" style={{ background: '#131920', border: '1px solid rgba(239,68,68,0.3)' }}>
      <p className="text-red-400 font-medium">Failed to load teams</p>
      <p className="text-sm mt-1" style={{ color: '#64748b' }}>{error}</p>
    </div>
  )

  const minEHI = Math.min(...teams.map(t => t.avg_EHI || 0))
  const maxEHI = Math.max(...teams.map(t => t.avg_EHI || 0))

  return (
    <div className="flex flex-col gap-6 max-w-6xl mx-auto">
      {/* Top section: list + player panel */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Team list */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <div className="px-4 py-3" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <h2 className="font-bold" style={{ color: '#f1f5f9' }}>All 30 Teams</h2>
            <p className="text-xs mt-0.5" style={{ color: '#64748b' }}>Click a team to see their players</p>
          </div>
          <div className="overflow-y-auto" style={{ maxHeight: 520 }}>
            {teams.map((team, i) => {
              const barColor = ehi_to_color(team.avg_EHI, minEHI, maxEHI)
              const isSelected = selectedTeam === team.team
              return (
                <button
                  key={team.team}
                  onClick={() => handleTeamClick(team)}
                  className="w-full flex items-center gap-3 px-4 py-3 text-left transition-all"
                  style={{
                    background: isSelected ? 'rgba(249,115,22,0.10)' : 'transparent',
                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                    borderLeft: isSelected ? '3px solid #f97316' : '3px solid transparent',
                  }}
                  onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)' }}
                  onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}
                >
                  <span className="text-xl font-black w-7 text-right flex-shrink-0" style={{ color: '#334155' }}>
                    {team.rank || i + 1}
                  </span>
                  <span className="text-lg font-black w-12 flex-shrink-0" style={{ color: '#f1f5f9' }}>
                    {team.team}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.08)' }}>
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${Math.min(100, (team.avg_EHI / (maxEHI * 1.05)) * 100)}%`, background: barColor }}
                      />
                    </div>
                  </div>
                  <span className="text-sm font-bold flex-shrink-0 w-12 text-right" style={{ color: barColor }}>
                    {team.avg_EHI?.toFixed(2)}
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Player panel */}
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <div className="px-4 py-3" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <h2 className="font-bold" style={{ color: '#f1f5f9' }}>
              {selectedTeam ? `${selectedTeam} — Players` : 'Select a team'}
            </h2>
            {selectedTeam && (
              <p className="text-xs mt-0.5" style={{ color: '#64748b' }}>Sorted by avg EHI descending</p>
            )}
          </div>

          {!selectedTeam && (
            <div className="flex items-center justify-center h-48">
              <p style={{ color: '#334155' }}>Click any team on the left</p>
            </div>
          )}

          {selectedTeam && loadingPlayers && <LoadingSpinner text="Loading players..." />}

          {selectedTeam && !loadingPlayers && (
            <div className="overflow-y-auto" style={{ maxHeight: 470 }}>
              {teamPlayers.length === 0 ? (
                <p className="p-6 text-center" style={{ color: '#64748b' }}>No player data found.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr style={{ background: '#1a2230', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                      {['Player', 'Pos', 'GP', 'PPG', 'Avg EHI'].map(h => (
                        <th key={h} className="px-3 py-2 text-left" style={{ color: '#64748b', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {teamPlayers.map((p, i) => (
                      <tr
                        key={p.player_id}
                        style={{
                          background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                          borderBottom: '1px solid rgba(255,255,255,0.04)',
                        }}
                      >
                        <td className="px-3 py-2.5">
                          <div className="flex items-center gap-2">
                            <PlayerHeadshot playerId={p.player_id} name={p.player_name} size={28} />
                            <span className="font-medium text-xs whitespace-nowrap" style={{ color: '#f1f5f9' }}>{p.player_name}</span>
                          </div>
                        </td>
                        <td className="px-3 py-2.5 text-xs" style={{ color: '#64748b' }}>
                          {POS_MAP[p.position] || '—'}
                        </td>
                        <td className="px-3 py-2.5 text-xs" style={{ color: '#94a3b8' }}>{p.gp}</td>
                        <td className="px-3 py-2.5 text-xs" style={{ color: '#94a3b8' }}>{p.avg_pts?.toFixed(1)}</td>
                        <td className="px-3 py-2.5">
                          <span className="font-bold text-sm" style={{ color: '#f97316' }}>
                            {p.avg_EHI?.toFixed(1)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Bar chart — all 30 teams */}
      <div
        className="rounded-xl p-4 pt-6"
        style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <h2 className="font-bold mb-4 px-2" style={{ color: '#f1f5f9' }}>All Teams — Avg EHI Bar Chart</h2>
        <ResponsiveContainer width="100%" height={Math.max(400, teams.length * 20)}>
          <BarChart
            data={[...teams]}
            layout="vertical"
            margin={{ top: 0, right: 60, bottom: 0, left: 40 }}
          >
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="rgba(255,255,255,0.05)" />
            <XAxis
              type="number"
              domain={[Math.max(0, minEHI - 2), maxEHI + 2]}
              tick={{ fill: '#64748b', fontSize: 11 }}
              tickLine={{ stroke: 'rgba(255,255,255,0.1)' }}
              axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
            />
            <YAxis
              dataKey="team"
              type="category"
              width={36}
              tick={{ fill: '#94a3b8', fontSize: 11, fontWeight: 600 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<CustomBarTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
            <Bar dataKey="avg_EHI" radius={[0, 3, 3, 0]}>
              {[...teams].map((t, i) => (
                <Cell key={t.team} fill={ehi_to_color(t.avg_EHI, minEHI, maxEHI)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
