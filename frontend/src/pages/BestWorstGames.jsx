import { useEffect, useState } from 'react'
import { fetchBestGames, fetchWorstGames } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import PlayerHeadshot from '../components/PlayerHeadshot'

const SCORE_COLORS = {
  SQS: '#3b82f6',
  FDS: '#a855f7',
  FTP: '#22c55e',
  SPS: '#fbbf24',
  DES: '#ef4444',
  SSS: '#06b6d4',
  EHI: '#f97316',
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T12:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function MiniBar({ value, color }) {
  const pct = Math.min(100, Math.max(0, (value / 100) * 100))
  return (
    <div className="flex items-center gap-1">
      <div className="w-8 h-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.08)' }}>
        <div style={{ width: `${pct}%`, background: color }} className="h-full rounded-full" />
      </div>
      <span className="text-xs tabular-nums" style={{ color: '#94a3b8' }}>{value?.toFixed(1)}</span>
    </div>
  )
}

function GamesTable({ games, mode }) {
  if (!games?.length) return <p className="text-center py-8" style={{ color: '#64748b' }}>No data available.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" style={{ minWidth: 900 }}>
        <thead>
          <tr style={{ background: '#1a2230', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            {['#', 'Player', 'Team', 'Opponent', 'Date', 'PTS', 'SQS', 'FDS', 'FTP', 'SPS', 'DES', 'SSS', 'EHI'].map(h => (
              <th
                key={h}
                className="px-3 py-3 text-left"
                style={{ color: '#64748b', fontSize: 11, letterSpacing: '0.05em', textTransform: 'uppercase', whiteSpace: 'nowrap' }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {games.map((g, i) => (
            <tr
              key={`${g.player_id}-${g.date}-${i}`}
              style={{
                background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.04)'}
              onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)'}
            >
              <td className="px-3 py-2.5" style={{ color: '#475569', fontSize: 12 }}>{i + 1}</td>
              <td className="px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <PlayerHeadshot playerId={g.player_id} name={g.player_name} size={30} />
                  <span className="font-medium whitespace-nowrap" style={{ color: '#f1f5f9' }}>{g.player_name}</span>
                </div>
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap" style={{ color: '#94a3b8' }}>{g.team}</td>
              <td className="px-3 py-2.5 whitespace-nowrap" style={{ color: '#64748b' }}>
                vs {g.opponent}
              </td>
              <td className="px-3 py-2.5 whitespace-nowrap" style={{ color: '#64748b' }}>{formatDate(g.date)}</td>
              <td className="px-3 py-2.5 font-medium" style={{ color: '#94a3b8' }}>{g.points}</td>
              <td className="px-3 py-2.5"><MiniBar value={g.SQS} color={SCORE_COLORS.SQS} /></td>
              <td className="px-3 py-2.5"><MiniBar value={g.FDS} color={SCORE_COLORS.FDS} /></td>
              <td className="px-3 py-2.5"><MiniBar value={g.FTP} color={SCORE_COLORS.FTP} /></td>
              <td className="px-3 py-2.5"><MiniBar value={g.SPS} color={SCORE_COLORS.SPS} /></td>
              <td className="px-3 py-2.5"><MiniBar value={g.DES} color={SCORE_COLORS.DES} /></td>
              <td className="px-3 py-2.5"><MiniBar value={g.SSS} color={SCORE_COLORS.SSS} /></td>
              <td className="px-3 py-2.5">
                <span
                  className="font-black text-base"
                  style={{ color: mode === 'best' ? '#f97316' : '#ef4444' }}
                >
                  {g.EHI?.toFixed(1)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function BestWorstGames({ season }) {
  const [tab, setTab] = useState('best')
  const [bestGames, setBestGames] = useState(null)
  const [worstGames, setWorstGames] = useState(null)
  const [loadingBest, setLoadingBest] = useState(true)
  const [loadingWorst, setLoadingWorst] = useState(true)
  const [errorBest, setErrorBest] = useState(null)
  const [errorWorst, setErrorWorst] = useState(null)

  useEffect(() => {
    setLoadingBest(true)
    setErrorBest(null)
    fetchBestGames(season, 50)
      .then(data => setBestGames(data.games || []))
      .catch(e => setErrorBest(e.message))
      .finally(() => setLoadingBest(false))

    setLoadingWorst(true)
    setErrorWorst(null)
    fetchWorstGames(season, 50)
      .then(data => setWorstGames(data.games || []))
      .catch(e => setErrorWorst(e.message))
      .finally(() => setLoadingWorst(false))
  }, [season])

  return (
    <div className="flex flex-col gap-4 max-w-full">
      {/* Tabs */}
      <div className="flex gap-2">
        {[
          { id: 'best', label: 'Top 50 Games', emoji: '🏆' },
          { id: 'worst', label: 'Bottom 50 Games', emoji: '📉' },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-all"
            style={{
              background: tab === t.id ? (t.id === 'best' ? '#f97316' : '#ef4444') : '#1a2230',
              color: tab === t.id ? '#fff' : '#94a3b8',
              border: '1px solid ' + (tab === t.id ? (t.id === 'best' ? '#f97316' : '#ef4444') : 'rgba(255,255,255,0.08)'),
            }}
          >
            {t.emoji} {t.label}
          </button>
        ))}
      </div>

      {/* Table card */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        {tab === 'best' && (
          loadingBest ? <LoadingSpinner text="Loading top games..." />
            : errorBest ? (
              <div className="p-6 text-center">
                <p className="text-red-400">{errorBest}</p>
              </div>
            ) : <GamesTable games={bestGames} mode="best" />
        )}
        {tab === 'worst' && (
          loadingWorst ? <LoadingSpinner text="Loading bottom games..." />
            : errorWorst ? (
              <div className="p-6 text-center">
                <p className="text-red-400">{errorWorst}</p>
              </div>
            ) : <GamesTable games={worstGames} mode="worst" />
        )}
      </div>
    </div>
  )
}
