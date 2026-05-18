import { useState, useEffect } from 'react'
import { fetchSeasons } from './api'
import Overview from './pages/Overview'
import PlayerLeaderboard from './pages/PlayerLeaderboard'
import ScatterPlot from './pages/ScatterPlot'
import BestWorstGames from './pages/BestWorstGames'
import TeamRankings from './pages/TeamRankings'
import Formula from './pages/Formula'

const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: '⬛' },
  { id: 'leaderboard', label: 'Player Leaderboard', icon: '🏅' },
  { id: 'scatter', label: 'Scatter Plot', icon: '📊' },
  { id: 'bestworst', label: 'Best & Worst Games', icon: '🎯' },
  { id: 'teams', label: 'Team Rankings', icon: '🏆' },
  { id: 'formula', label: 'The Formula', icon: '🔬' },
]

const PAGE_TITLES = {
  overview: 'Overview',
  leaderboard: 'Player Leaderboard',
  scatter: 'EHI Scatter Plot',
  bestworst: 'Best & Worst Games',
  teams: 'Team Rankings',
  formula: 'The Formula',
}

export default function App() {
  const [page, setPage] = useState('overview')
  const [season, setSeason] = useState('2025-26')
  const [seasons, setSeasons] = useState(['2025-26'])
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    fetchSeasons()
      .then(data => {
        if (data.seasons && data.seasons.length > 0) {
          setSeasons(data.seasons)
          setSeason(data.seasons[0])
        }
      })
      .catch(() => {})
  }, [])

  const navigate = (id) => {
    setPage(id)
    setSidebarOpen(false)
  }

  const renderPage = () => {
    switch (page) {
      case 'overview': return <Overview season={season} />
      case 'leaderboard': return <PlayerLeaderboard season={season} />
      case 'scatter': return <ScatterPlot season={season} />
      case 'bestworst': return <BestWorstGames season={season} />
      case 'teams': return <TeamRankings season={season} />
      case 'formula': return <Formula />
      default: return <Overview season={season} />
    }
  }

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#0d1117' }}>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-20 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed lg:static inset-y-0 left-0 z-30 flex flex-col transition-transform duration-300 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
        style={{
          width: 240,
          background: '#0d1117',
          borderRight: '1px solid rgba(255,255,255,0.06)',
          flexShrink: 0,
        }}
      >
        {/* Logo */}
        <div className="px-5 py-6" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <div className="flex items-center gap-2">
            <span className="text-3xl">🏀</span>
            <div>
              <div className="text-2xl font-black tracking-tight" style={{ color: '#f97316', lineHeight: 1 }}>
                EHI
              </div>
              <div className="text-xs font-medium" style={{ color: '#64748b' }}>
                Ethical Hoops Index
              </div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 overflow-y-auto">
          {NAV_ITEMS.map(item => {
            const active = page === item.id
            return (
              <button
                key={item.id}
                onClick={() => navigate(item.id)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg mb-1 text-left transition-all duration-150"
                style={{
                  background: active ? 'rgba(249,115,22,0.10)' : 'transparent',
                  borderLeft: active ? '3px solid #f97316' : '3px solid transparent',
                  color: active ? '#f1f5f9' : '#64748b',
                  fontSize: 14,
                  fontWeight: active ? 600 : 400,
                }}
                onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'rgba(255,255,255,0.04)' }}
                onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{ fontSize: 16 }}>{item.icon}</span>
                {item.label}
              </button>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="px-5 py-4" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <p className="text-xs" style={{ color: '#334155' }}>
            2025-26 NBA Season<br />
            v1.0 · Built with EHI
          </p>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top navbar */}
        <header
          className="flex items-center justify-between px-4 lg:px-6 h-14 flex-shrink-0"
          style={{
            background: '#131920',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}
        >
          <div className="flex items-center gap-3">
            {/* Hamburger (mobile) */}
            <button
              className="lg:hidden p-1.5 rounded"
              style={{ color: '#94a3b8' }}
              onClick={() => setSidebarOpen(true)}
            >
              <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path d="M3 12h18M3 6h18M3 18h18" />
              </svg>
            </button>
            <h1 className="text-base font-semibold" style={{ color: '#f1f5f9' }}>
              {PAGE_TITLES[page]}
            </h1>
          </div>

          {/* Season selector */}
          <div className="flex items-center gap-2">
            <label className="text-xs" style={{ color: '#64748b' }}>Season</label>
            <select
              value={season}
              onChange={e => setSeason(e.target.value)}
              className="text-sm rounded px-2 py-1 outline-none"
              style={{
                background: '#1a2230',
                border: '1px solid rgba(255,255,255,0.10)',
                color: '#f1f5f9',
              }}
            >
              {seasons.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          {renderPage()}
        </main>
      </div>
    </div>
  )
}
