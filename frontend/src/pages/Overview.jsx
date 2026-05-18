import { useEffect, useState } from 'react'
import { fetchSummary } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import PlayerHeadshot from '../components/PlayerHeadshot'
import ScoreBar from '../components/ScoreBar'

const SCORE_COLORS = {
  SQS: '#3b82f6',
  FDS: '#a855f7',
  FTP: '#22c55e',
  SPS: '#fbbf24',
  DES: '#ef4444',
  SSS: '#06b6d4',
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function StatCard({ label, children, className = '' }) {
  return (
    <div
      className={`rounded-xl p-5 flex flex-col gap-1 ${className}`}
      style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
    >
      <p className="text-xs font-medium uppercase tracking-wider" style={{ color: '#64748b' }}>{label}</p>
      {children}
    </div>
  )
}

function StarCard({ player, rank }) {
  const medals = ['🥇', '🥈', '🥉']
  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ background: '#1a2230', border: '1px solid rgba(255,255,255,0.06)' }}
    >
      <div className="flex items-center gap-3">
        <span className="text-xl">{medals[rank]}</span>
        <PlayerHeadshot playerId={player.player_id} name={player.player_name} size={52} />
        <div className="min-w-0">
          <p className="font-bold text-sm truncate" style={{ color: '#f1f5f9' }}>{player.player_name}</p>
          <p className="text-xs" style={{ color: '#64748b' }}>
            {player.team} · {formatDate(player.date)}
          </p>
          <p className="text-xs" style={{ color: '#94a3b8' }}>{player.points} PTS</p>
        </div>
        <div className="ml-auto text-right flex-shrink-0">
          <p className="text-2xl font-black" style={{ color: '#f97316' }}>{player.EHI?.toFixed(1)}</p>
          <p className="text-xs" style={{ color: '#64748b' }}>EHI</p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-x-2 gap-y-1">
        {['SQS', 'FDS', 'FTP', 'SPS', 'DES', 'SSS'].map(key => (
          <div key={key} className="flex items-center justify-between gap-1">
            <span className="text-xs font-medium" style={{ color: '#64748b', width: 28 }}>{key}</span>
            <ScoreBar value={player[key]} color={SCORE_COLORS[key]} />
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Overview({ season }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchSummary(season)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [season])

  if (loading) return <LoadingSpinner text="Loading season summary..." />
  if (error) return (
    <div className="rounded-xl p-6 text-center" style={{ background: '#131920', border: '1px solid rgba(239,68,68,0.3)' }}>
      <p className="text-red-400 font-medium">Failed to load data</p>
      <p className="text-sm mt-1" style={{ color: '#64748b' }}>{error}</p>
    </div>
  )
  if (!data) return null

  const topPlayer = data.top_10_games?.[0]
  const topTeam = data.teams?.[0]

  return (
    <div className="flex flex-col gap-6 max-w-6xl mx-auto">
      {/* Hero stat row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="League Average EHI">
          <p className="text-5xl font-black" style={{ color: '#f97316' }}>
            {data.league_avg_ehi?.toFixed(2)}
          </p>
          <p className="text-sm mt-1" style={{ color: '#94a3b8' }}>{season} Regular Season</p>
          <p className="text-xs" style={{ color: '#64748b' }}>
            {data.player_game_count?.toLocaleString()} player-game rows
          </p>
        </StatCard>

        <StatCard label="Top Performer (Single Game)">
          {topPlayer ? (
            <div className="flex items-center gap-3 mt-1">
              <PlayerHeadshot playerId={topPlayer.player_id} name={topPlayer.player_name} size={56} />
              <div>
                <p className="font-bold" style={{ color: '#f1f5f9' }}>{topPlayer.player_name}</p>
                <p className="text-xs" style={{ color: '#64748b' }}>{topPlayer.team} · {formatDate(topPlayer.date)}</p>
                <p className="text-2xl font-black mt-1" style={{ color: '#f97316' }}>
                  {topPlayer.EHI?.toFixed(1)} EHI
                </p>
              </div>
            </div>
          ) : <p className="text-slate-400">No data</p>}
        </StatCard>

        <StatCard label="Most Ethical Team">
          {topTeam ? (
            <div className="mt-1">
              <p className="text-5xl font-black tracking-tight" style={{ color: '#fbbf24' }}>{topTeam.team}</p>
              <p className="text-2xl font-bold mt-1" style={{ color: '#f97316' }}>
                {topTeam.avg_EHI?.toFixed(2)} avg EHI
              </p>
              <p className="text-xs mt-1" style={{ color: '#64748b' }}>{topTeam.gp} games played</p>
            </div>
          ) : <p className="text-slate-400">No data</p>}
        </StatCard>
      </div>

      {/* What is EHI */}
      <div
        className="rounded-xl p-6"
        style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <h2 className="text-lg font-bold mb-3" style={{ color: '#f1f5f9' }}>What is the Ethical Hoops Index?</h2>
        <p className="text-sm leading-relaxed mb-3" style={{ color: '#94a3b8' }}>
          The <span style={{ color: '#fbbf24', fontWeight: 600 }}>Ethical Hoops Index</span> measures how ethically an NBA player performed on a given night. It's not just about counting stats — it's about <em style={{ color: '#f1f5f9' }}>how</em> those stats were generated. A player who scores 30 points on efficient self-created shots with disciplined defense rates higher than one who draws 15 free throws through gimmicky contact-hunting.
        </p>
        <p className="text-sm leading-relaxed mb-3" style={{ color: '#94a3b8' }}>
          EHI combines six sub-scores covering shot quality, foul drawing legitimacy, free throw dependency, sportsmanship, defensive effort, and scoring skill. Each score reflects a different dimension of "good basketball" — playing hard, playing fair, and actually trying to win rather than gaming referee attention.
        </p>
        <p className="text-sm leading-relaxed" style={{ color: '#94a3b8' }}>
          The result is an absolute per-game metric, not adjusted for opponent or schedule. A great EHI game means you played the game the right way — efficient offense, active defense, clean conduct.
        </p>
        <div
          className="mt-4 rounded-lg px-4 py-3 font-mono text-sm"
          style={{ background: '#1a2230', color: '#fbbf24' }}
        >
          EHI = 0.35(SQS) + 0.20(FDS) + 0.20(FTP) + 0.05(SPS) + 0.05(DES) + 0.15(SSS)
        </div>
      </div>

      {/* The Inspiration */}
      <div
        className="rounded-xl p-6"
        style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <h2 className="text-lg font-bold mb-3" style={{ color: '#f1f5f9' }}>The Inspiration</h2>
        <p className="text-sm leading-relaxed" style={{ color: '#94a3b8' }}>
          The NBA has long debated what "good basketball" really looks like. Is drawing 15 free throws through jump-into-the-defender moves a skill, or gaming the system? Is chucking up mid-range bricks with high volume respectable, or wasteful? Are players who refuse to shoot from range letting their teammates down, or playing within their limitations? EHI tries to answer these questions with data — rewarding players who get their points the hard, clean way.
        </p>
      </div>

      {/* Star Performers */}
      <div>
        <h2 className="text-lg font-bold mb-3" style={{ color: '#f1f5f9' }}>
          Top Single-Game Performances
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {data.top_10_games?.slice(0, 3).map((player, i) => (
            <StarCard key={`${player.player_id}-${player.date}`} player={player} rank={i} />
          ))}
        </div>
      </div>

      {/* Top 5 Teams */}
      <div>
        <h2 className="text-lg font-bold mb-3" style={{ color: '#f1f5f9' }}>Top 5 Teams by Avg EHI</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {data.teams?.slice(0, 5).map((team, i) => (
            <div
              key={team.team}
              className="rounded-xl p-4 flex flex-col gap-2"
              style={{ background: '#1a2230', border: '1px solid rgba(255,255,255,0.06)' }}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium" style={{ color: '#64748b' }}>#{i + 1}</span>
                <span className="text-xs" style={{ color: '#64748b' }}>{team.gp} GP</span>
              </div>
              <p className="text-2xl font-black tracking-tight" style={{ color: '#fbbf24' }}>{team.team}</p>
              <div>
                <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.08)' }}>
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${Math.min(100, (team.avg_EHI / 70) * 100)}%`, background: '#f97316' }}
                  />
                </div>
                <p className="text-lg font-bold mt-1" style={{ color: '#f97316' }}>
                  {team.avg_EHI?.toFixed(2)}
                </p>
                <p className="text-xs" style={{ color: '#64748b' }}>avg EHI</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
