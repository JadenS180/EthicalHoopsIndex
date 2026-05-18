const SUBSCORE_CARDS = [
  {
    code: 'SQS',
    name: 'Shot Quality Score',
    weight: '35%',
    color: '#3b82f6',
    description:
      'Did the player take shots a skilled, ethical player would take? SQS rewards contested makes and self-created quality looks — the kinds of shots only a skilled player can generate. It punishes low-efficiency chucking, especially repeated attempts from low-xeFG zones.',
    earns: 'Contested makes, self-created shots in high-xeFG zones, high-volume efficiency (15+ shots above position threshold)',
    loses: 'Low-xeFG chucks from unfavorable zones, repeated attempts with poor shot selection',
  },
  {
    code: 'FDS',
    name: 'Foul Drawing Score',
    weight: '20%',
    color: '#a855f7',
    description:
      'Did the player earn their free throws, or manufacture them? FDS assesses the legitimacy of every foul drawn using defender proximity data, whether the shot was assisted (catch-and-shoot), and whether it resulted in an and-1. It also checks for repetitive exploitation of the same foul type.',
    earns: 'Drawing fouls under heavy defensive pressure, and-1 completions, catch-and-shoot fouls, center drawing paint contact',
    loses: 'Jump-into-defender moves with no contest, repeated off-ball fouls, garbage-time free throw manufacturing, guard baiting 3-point fouls',
  },
  {
    code: 'FTP',
    name: 'FT Dependency Score',
    weight: '20%',
    color: '#22c55e',
    description:
      'How much of a player\'s scoring came from free throws vs. live-ball offense? FTP penalizes players who are heavily FT-dependent while rewarding volume scorers who get their points efficiently in the flow of the game. Elite playmakers receive a bonus for assists.',
    earns: 'High-volume live-ball scoring, elite assist totals, creating for teammates',
    loses: 'Scoring almost entirely from the free throw line, low assist totals paired with FT dependency',
  },
  {
    code: 'SPS',
    name: 'Sportsmanship Score',
    weight: '5%',
    color: '#fbbf24',
    description:
      'Did the player conduct themselves with integrity? SPS is the only sub-score with a hard floor — it starts at 100 and only goes down. Penalties apply exponentially, so a player who racks up multiple violations of the same type gets punished more severely for each one.',
    earns: 'Clean game with no violations (stays at 100 baseline)',
    loses: 'Technical fouls (−18), flagrant fouls, illegal screens, delay-of-game violations. Each repeated violation of the same type stacks harder.',
  },
  {
    code: 'DES',
    name: 'Defensive Effort Score',
    weight: '5%',
    color: '#ef4444',
    description:
      'Did the player compete on defense? DES rewards active, disruptive defenders across every category of hustle play — contested shots, deflections, steals, blocks, defensive rebounds, and charges taken. Normalization is position-adjusted so guards, forwards, and centers are evaluated against realistic baselines.',
    earns: 'Contested shots, deflections, steals, blocks, defensive rebounds, charges drawn',
    loses: 'Foul trouble (especially offensive fouls), zero defensive activity',
  },
  {
    code: 'SSS',
    name: 'Scoring Skill Score',
    weight: '15%',
    color: '#06b6d4',
    description:
      'Did the player create their own offense and facilitate for others? SSS rewards unassisted (self-created) points — especially from high-difficulty looks — and treats every assist as evidence of basketball intelligence and unselfishness.',
    earns: 'Self-created buckets from quality zones (xeFG ≥ 0.50), high assist totals, shot creation without relying on set-up passes',
    loses: 'Scoring entirely off assisted shots with zero playmaking (baseline 20 for zero shots/assists)',
  },
]

const FUTURE_ITEMS = [
  'Opponent quality adjustment — EHI scores are currently absolute, not strength-of-schedule adjusted. A guard defending elite shooters gets the same DES credit as one defending a league-worst bench.',
  'Per-shot defender distance — Defender proximity is currently derived from season-level PlayerDashPtShots bucket distributions, not from per-shot data. Shot Chart Detail does not return per-shot proximity.',
  'Positional bias fix for low-usage big men — Centers dominate season leaderboards because high DES + neutral FTP baseline inflates EHI for bigs who barely score. An offensive usage floor or FGA-based reweighting is planned.',
  'Playoff expansion — Regular season only for now. Playoff basketball has different intensity and officiating patterns that may require formula recalibration.',
  'Historical seasons — The current empirical xeFG% table and calibration targets are based on 2025-26. Historical runs would require per-season recalibration.',
]

function SubScoreCard({ card }) {
  return (
    <div
      className="rounded-xl p-5 flex flex-col gap-3"
      style={{ background: '#1a2230', border: `1px solid ${card.color}22` }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center font-black text-sm"
            style={{ background: card.color + '22', color: card.color }}
          >
            {card.code}
          </div>
          <div>
            <p className="font-bold text-sm" style={{ color: '#f1f5f9' }}>{card.name}</p>
            <p className="text-xs" style={{ color: '#64748b' }}>Weight: {card.weight}</p>
          </div>
        </div>
        <div
          className="px-2 py-1 rounded text-xs font-bold"
          style={{ background: card.color + '22', color: card.color }}
        >
          {card.weight}
        </div>
      </div>
      <p className="text-sm leading-relaxed" style={{ color: '#94a3b8' }}>{card.description}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div className="rounded-lg p-3" style={{ background: 'rgba(34,197,94,0.07)', border: '1px solid rgba(34,197,94,0.15)' }}>
          <p className="text-xs font-semibold mb-1" style={{ color: '#22c55e' }}>What earns points</p>
          <p className="text-xs leading-relaxed" style={{ color: '#86efac' }}>{card.earns}</p>
        </div>
        <div className="rounded-lg p-3" style={{ background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.15)' }}>
          <p className="text-xs font-semibold mb-1" style={{ color: '#ef4444' }}>What loses points</p>
          <p className="text-xs leading-relaxed" style={{ color: '#fca5a5' }}>{card.loses}</p>
        </div>
      </div>
    </div>
  )
}

export default function Formula() {
  return (
    <div className="flex flex-col gap-8 max-w-4xl mx-auto">
      {/* Section 1 — The Formula */}
      <section>
        <h2 className="text-2xl font-black mb-4" style={{ color: '#f1f5f9' }}>The EHI Formula</h2>
        <div
          className="rounded-xl p-6 text-center"
          style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <p className="font-mono text-lg md:text-2xl font-bold tracking-tight leading-loose" style={{ color: '#fbbf24' }}>
            EHI = 0.35×SQS + 0.20×FDS + 0.20×FTP
          </p>
          <p className="font-mono text-lg md:text-2xl font-bold tracking-tight" style={{ color: '#fbbf24' }}>
            + 0.05×SPS + 0.05×DES + 0.15×SSS
          </p>
          <p className="text-sm mt-4" style={{ color: '#64748b' }}>
            An absolute per-game metric. Higher = played the game more ethically.
          </p>
        </div>

        {/* Weight breakdown */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-4">
          {SUBSCORE_CARDS.map(c => (
            <div
              key={c.code}
              className="rounded-lg p-3 flex items-center gap-3"
              style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
            >
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center font-black text-xs flex-shrink-0"
                style={{ background: c.color + '22', color: c.color }}
              >
                {c.code}
              </div>
              <div>
                <p className="text-xs font-medium" style={{ color: '#f1f5f9' }}>{c.name}</p>
                <p className="text-xs" style={{ color: c.color }}>{c.weight}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Section 2 — The Inspiration */}
      <section>
        <h2 className="text-2xl font-black mb-4" style={{ color: '#f1f5f9' }}>The Inspiration</h2>
        <div
          className="rounded-xl p-6 flex flex-col gap-4"
          style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <p className="text-sm leading-relaxed" style={{ color: '#94a3b8' }}>
            For most of the 2010s, <span style={{ color: '#fbbf24', fontWeight: 600 }}>James Harden</span> represented a new kind of player — one who had mastered the art of drawing fouls rather than simply scoring. Stepping into defenders on 3-point attempts, pump-faking and falling backward into outstretched arms, baiting off-ball contact on inbounds plays. Harden was brilliant, and his volume of free throw attempts was genuinely unprecedented. But was it skill, or was it gaming a system that wasn't designed to reward this kind of optimization?
          </p>
          <p className="text-sm leading-relaxed" style={{ color: '#94a3b8' }}>
            <span style={{ color: '#fbbf24', fontWeight: 600 }}>Luka Doncic</span> brought a European version of the same controversy — the jump-into-the-defender three-point foul, perfected at the left elbow, drawing automatic trips to the line from what appeared to be perfectly legal defensive positioning. The NBA eventually legislated some of these plays out of the game, but the philosophical question remained: is exploiting referee conventions a basketball skill worthy of reward, or a form of manipulation that undermines competitive integrity?
          </p>
          <p className="text-sm leading-relaxed" style={{ color: '#94a3b8' }}>
            On the other end, <span style={{ color: '#fbbf24', fontWeight: 600 }}>Ben Simmons</span> spent his Philadelphia years refusing to shoot from mid-range or beyond, effectively making himself a liability at the free throw line and constraining his team's offensive floor spacing. Whether through lack of confidence or something else, he was choosing passivity over competition — a different kind of failure to honor the game's implicit social contract.
          </p>
          <p className="text-sm leading-relaxed" style={{ color: '#94a3b8' }}>
            Basketball has an implicit social contract: play hard, play fair, try to win by playing better basketball. EHI was built to create a data-driven answer to whether players are honoring that contract — not just by counting what they did, but by weighing <em style={{ color: '#f1f5f9' }}>how</em> they did it.
          </p>
        </div>
      </section>

      {/* Section 3 — Sub-score explainers */}
      <section>
        <h2 className="text-2xl font-black mb-4" style={{ color: '#f1f5f9' }}>Sub-Score Breakdown</h2>
        <div className="flex flex-col gap-4">
          {SUBSCORE_CARDS.map(card => <SubScoreCard key={card.code} card={card} />)}
        </div>
      </section>

      {/* Section 4 — Future improvements */}
      <section>
        <h2 className="text-2xl font-black mb-4" style={{ color: '#f1f5f9' }}>Future Improvements</h2>
        <div
          className="rounded-xl p-6"
          style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <ul className="flex flex-col gap-3">
            {FUTURE_ITEMS.map((item, i) => (
              <li key={i} className="flex gap-3">
                <span className="text-orange-500 mt-0.5 flex-shrink-0">→</span>
                <p className="text-sm leading-relaxed" style={{ color: '#94a3b8' }}>{item}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Section 5 — Full reference */}
      <section>
        <h2 className="text-2xl font-black mb-4" style={{ color: '#f1f5f9' }}>Full Technical Reference</h2>
        <div
          className="rounded-xl p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
          style={{ background: '#131920', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <div>
            <p className="font-semibold" style={{ color: '#f1f5f9' }}>EHI Master Reference</p>
            <p className="text-sm mt-1" style={{ color: '#64748b' }}>
              Complete formula documentation, constant values, design decisions, and validation results.
            </p>
          </div>
          <a
            href="https://github.com/JadenS180/EthicalHoopsIndex/blob/main/EHI_Master_Reference.md"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg font-semibold text-sm transition-all flex-shrink-0"
            style={{
              background: '#f97316',
              color: '#fff',
              textDecoration: 'none',
            }}
            onMouseEnter={e => e.currentTarget.style.background = '#ea6c0e'}
            onMouseLeave={e => e.currentTarget.style.background = '#f97316'}
          >
            EHI Master Reference
            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" />
            </svg>
          </a>
        </div>
      </section>
    </div>
  )
}
