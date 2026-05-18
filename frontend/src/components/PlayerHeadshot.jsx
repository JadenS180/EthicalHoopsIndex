import { useState } from 'react'

export default function PlayerHeadshot({ playerId, name, size = 40 }) {
  const [failed, setFailed] = useState(false)
  const initials = name?.split(' ').map(w => w[0]).join('').slice(0, 2) || '?'

  if (failed || !playerId) {
    return (
      <div
        style={{ width: size, height: size }}
        className="rounded-full bg-navy-700 border border-white/10 flex items-center justify-center flex-shrink-0"
      >
        <span style={{ fontSize: size * 0.35 }} className="text-amber-400 font-bold">
          {initials}
        </span>
      </div>
    )
  }

  return (
    <div
      style={{ width: size, height: size }}
      className="rounded-full overflow-hidden flex-shrink-0 border border-white/10"
    >
      <img
        src={`https://cdn.nba.com/headshots/nba/latest/1040x760/${playerId}.png`}
        alt={name}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          objectPosition: 'top center',
        }}
        onError={() => setFailed(true)}
      />
    </div>
  )
}
