const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function apiFetch(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json()
}

export const fetchSeasons = () => apiFetch('/api/seasons')
export const fetchSummary = (season) => apiFetch(`/api/season/${season}/summary`)
export const fetchPlayers = (season, params = {}) =>
  apiFetch(`/api/season/${season}/players?${new URLSearchParams(params)}`)
export const fetchTeams = (season) => apiFetch(`/api/season/${season}/teams`)
export const fetchBestGames = (season, n = 50) => apiFetch(`/api/season/${season}/best-games?n=${n}`)
export const fetchWorstGames = (season, n = 50) => apiFetch(`/api/season/${season}/worst-games?n=${n}`)
export const fetchGameLeaderboard = (gameId) => apiFetch(`/api/game/${gameId}/leaderboard`)
