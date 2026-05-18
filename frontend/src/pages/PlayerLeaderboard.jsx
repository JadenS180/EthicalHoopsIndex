import { useEffect, useState, useMemo } from 'react'
import { fetchPlayers } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import PlayerHeadshot from '../components/PlayerHeadshot'
import ScoreBar from '../components/ScoreBar'

const SCORE_COLORS = {
  avg_SQS: '#3b82f6',
  avg_FDS: '#a855f7',
  avg_FTP: '#22c55e',
  avg_SPS: '#fbbf24',
  avg_DES: '#ef4444',
  avg_SSS: '#06b6d4',
  avg_EHI: '#f97316',
}

const COLUMNS = [
  { key: 'rank', label: '#', sortable: false },
  { key: 'player_name', label: 'Player', sortable: true },
  { key: 'team', label: 'Team', sortable: true },
  { key: 'position', label: 'Pos', sortable: true },
  { key: 'gp', label: 'GP', sortable: true },
  { key: 'avg_pts', label: 'PPG', sortable: true },
  { key: 'avg_SQS', label: 'SQS', sortable: true },
  { key: 'avg_FDS', label: 'FDS', sortable: true },
  { key: 'avg_FTP', label: 'FTP', sortable: true },
  { key: 'avg_SPS', label: 'SPS', sortable: true },
  { key: 'avg_DES', label: 'DES', sortable: true },
  { key: 'avg_SSS', label: 'SSS', sortable: true },
  { key: 'avg_EHI', label: 'EHI', sortable: true },
]

const POS_MAP = { center: 'C', forward: 'F', guard: 'G' }

const ROLE_OPTIONS = [
  { value: '', label: 'All Roles' },
  { value: 'star', label: 'Stars (15+ PPG)' },
  { value: 'role', label: 'Role Players' },
  { value: 'bench', label: 'Bench (<8 PPG)' },
]

function SortIcon({ direction }) {
  if (!direction) return <span style={{ color: '#334155', fontSize: 10 }}>⇅</span>
  return <span style={{ color: '#f97316', fontSize: 10 }}>{direction === 'asc' ? '↑' : '↓'}</span>
}

export default function PlayerLeaderboard({ season }) {
  const [players, setPlayers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [teamFilter, setTeamFilter] = useState('')
  const [posFilter, setPosFilter] = useState('')
  const [sortKey, setSortKey] = useState('avg_EHI')
  const [sortDir, setSortDir] = useState('desc')
  const [minGamesFilter, setMinGamesFilter] = useState(true)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setSearch('')
    setRole('')
    setTeamFilter('')
    setPosFilter('')
    fetchPlayers(season, { min_games: 1 })
      .then(data => setPlayers(data.players || []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [season])

  const teams = useMemo(() => {
    const set = new Set(players.map(p => p.team).filter(Boolean))
    return Array.from(set).sort()
  }, [players])

  const filtered = useMemo(() => {
    let result = [...players]
    if (minGamesFilter) result = result.filter(p => p.gp >= 20)
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(p => p.player_name?.toLowerCase().includes(q))
    }
    if (role === 'star') result = result.filter(p => p.avg_pts >= 15)
    else if (role === 'role') result = result.filter(p => p.avg_pts >= 8 && p.avg_pts < 15)
    else if (role === 'bench') result = result.filter(p => p.avg_pts < 8)
    if (teamFilter) result = result.filter(p => p.team === teamFilter)
    if (posFilter) result = result.filter(p => p.position === posFilter)
    result.sort((a, b) => {
      const av = a[sortKey] ?? 0
      const bv = b[sortKey] ?? 0
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
      return sortDir === 'asc' ? av - bv : bv - av
    })
    return result
  }, [players, search, role, teamFilter, posFilter, sortKey, sortDir])

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  if (loading) return <LoadingSpinner text="Loading player data..." />
  if (error) return (
    <div className="rounded-xl p-6 text-center" style={{ background: '#131920', border: '1px solid rgba(239,68,68,0.3)' }}>
      <p className="text-red-400 font-medium">Failed to load players</p>
      <p className="text-sm mt-1" style={{ color: '#64748b' }}>{error}</p>
    </div>
  )

  return (
    <div className="flex flex-col gap-4 max-w-full">
      {/* Controls */}
      <div
        className="rounded-xl p-4 flex flex-wrap gap-3 items-center"
        style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <input
          type="text"
          placeholder="Search players..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="rounded-lg px-3 py-2 text-sm outline-none flex-1 min-w-48"
          style={{ background: '#1a2230', border: '1px solid rgba(255,255,255,0.10)', color: '#f1f5f9' }}
        />
        <select
          value={role}
          onChange={e => setRole(e.target.value)}
          className="rounded-lg px-3 py-2 text-sm outline-none"
          style={{ background: '#1a2230', border: '1px solid rgba(255,255,255,0.10)', color: '#f1f5f9' }}
        >
          {ROLE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select
          value={teamFilter}
          onChange={e => setTeamFilter(e.target.value)}
          className="rounded-lg px-3 py-2 text-sm outline-none"
          style={{ background: '#1a2230', border: '1px solid rgba(255,255,255,0.10)', color: '#f1f5f9' }}
        >
          <option value="">All Teams</option>
          {teams.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select
          value={posFilter}
          onChange={e => setPosFilter(e.target.value)}
          className="rounded-lg px-3 py-2 text-sm outline-none"
          style={{ background: '#1a2230', border: '1px solid rgba(255,255,255,0.10)', color: '#f1f5f9' }}
        >
          <option value="">All Positions</option>
          <option value="guard">Guard</option>
          <option value="forward">Forward</option>
          <option value="center">Center</option>
        </select>
        <button
          onClick={() => setMinGamesFilter(v => !v)}
          className="rounded-lg px-3 py-2 text-xs font-medium transition-all flex-shrink-0"
          style={{
            background: minGamesFilter ? 'rgba(249,115,22,0.15)' : '#1a2230',
            border: '1px solid ' + (minGamesFilter ? '#f97316' : 'rgba(255,255,255,0.10)'),
            color: minGamesFilter ? '#f97316' : '#64748b',
          }}
        >
          {minGamesFilter ? 'Min 20 games' : 'All players'}
        </button>
        <span className="text-sm ml-auto flex-shrink-0" style={{ color: '#64748b' }}>
          {filtered.length} players
        </span>
      </div>

      {/* Table */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm" style={{ minWidth: 900 }}>
            <thead>
              <tr style={{ background: '#1a2230', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                {COLUMNS.map(col => (
                  <th
                    key={col.key}
                    className={`px-3 py-3 text-left font-semibold ${col.key === 'player_name' ? 'sticky left-0 z-10' : ''}`}
                    style={{
                      color: '#64748b',
                      fontSize: 11,
                      letterSpacing: '0.05em',
                      textTransform: 'uppercase',
                      cursor: col.sortable ? 'pointer' : 'default',
                      background: '#1a2230',
                      userSelect: 'none',
                      whiteSpace: 'nowrap',
                    }}
                    onClick={() => col.sortable && handleSort(col.key)}
                  >
                    <span className="flex items-center gap-1">
                      {col.label}
                      {col.sortable && <SortIcon direction={sortKey === col.key ? sortDir : null} />}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((player, i) => (
                <tr
                  key={player.player_id}
                  style={{
                    background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.04)'}
                  onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)'}
                >
                  <td className="px-3 py-2.5" style={{ color: '#475569', fontSize: 12 }}>{i + 1}</td>
                  <td
                    className="px-3 py-2.5 sticky left-0"
                    style={{ background: i % 2 === 0 ? '#131920' : '#141b22' }}
                  >
                    <div className="flex items-center gap-2">
                      <PlayerHeadshot playerId={player.player_id} name={player.player_name} size={32} />
                      <span className="font-medium whitespace-nowrap" style={{ color: '#f1f5f9' }}>
                        {player.player_name}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap" style={{ color: '#94a3b8' }}>{player.team}</td>
                  <td className="px-3 py-2.5" style={{ color: '#64748b' }}>
                    {POS_MAP[player.position] || player.position || '—'}
                  </td>
                  <td className="px-3 py-2.5" style={{ color: '#94a3b8' }}>{player.gp}</td>
                  <td className="px-3 py-2.5" style={{ color: '#94a3b8' }}>{player.avg_pts?.toFixed(1)}</td>
                  {['avg_SQS', 'avg_FDS', 'avg_FTP', 'avg_SPS', 'avg_DES', 'avg_SSS'].map(key => (
                    <td key={key} className="px-3 py-2.5">
                      <ScoreBar value={player[key]} color={SCORE_COLORS[key]} />
                    </td>
                  ))}
                  <td className="px-3 py-2.5">
                    <span className="font-bold" style={{ color: '#f97316' }}>
                      {player.avg_EHI?.toFixed(1)}
                    </span>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={13} className="px-3 py-12 text-center" style={{ color: '#475569' }}>
                    No players match your filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
