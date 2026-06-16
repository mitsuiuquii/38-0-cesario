import React from "react";

/** Knockout bracket visualizer for Copa do Brasil and continental cups. */
export default function CupBracket({ comp, sim, myTeamId }) {
  if (!comp || !comp.bracket) return null;
  const stages = comp.bracket.stages || [];
  return (
    <div className="glass p-4 overflow-x-auto" data-testid={`bracket-${comp.id}`}>
      <h3 className="font-anton uppercase text-xl mb-3">{comp.name} — Chaveamento</h3>
      <div className="flex gap-6 min-w-fit">
        {stages.map((stage, sIdx) => (
          <div key={sIdx} className="flex flex-col gap-3 min-w-[180px]">
            <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">
              {stage.name}
            </div>
            {stage.matchups.map((mu, mIdx) => {
              const [a, b, tieId] = mu;
              const teamA = sim.teams[a];
              const teamB = sim.teams[b];
              // Find the corresponding match in phases for live score
              const allMatches = comp.phases.flatMap((p) => p.matches);
              const candidateMatches = allMatches.filter(
                (m) => (m.home_id === a && m.away_id === b) || (m.home_id === b && m.away_id === a)
              );
              const m = tieId
                ? candidateMatches.find((mm) => mm.tie_id === tieId && mm.leg === (sIdx % 2 === 0 ? 1 : 2)) || candidateMatches[0]
                : candidateMatches[0];
              const tie = tieId ? comp.ties?.[tieId] : null;
              const isMine = a === myTeamId || b === myTeamId;
              return (
                <div
                  key={mIdx}
                  className={`rounded-md p-2 text-xs font-oswald ${isMine ? "border border-[var(--neon)]" : "border border-white/5"} bg-black/30`}
                  data-testid={`bracket-match-${comp.id}-${sIdx}-${mIdx}`}
                >
                  <div className="flex justify-between items-center">
                    <span className="truncate flex-1">{teamA?.teamName || a}</span>
                    <span className="font-anton mx-2">{m?.home_id === a ? m?.home_score : m?.away_score ?? "-"}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="truncate flex-1">{teamB?.teamName || b}</span>
                    <span className="font-anton mx-2">{m?.home_id === b ? m?.home_score : m?.away_score ?? "-"}</span>
                  </div>
                  {tie && (
                    <div className="text-[10px] text-slate-400 mt-1">
                      Agregado: {tie.agg_a}-{tie.agg_b}
                      {tie.winner_id && (
                        <span className="ml-1 text-[var(--neon)]">
                          • {sim.teams[tie.winner_id]?.teamName} classificado
                        </span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      {comp.winner_id && (
        <div className="mt-3 font-anton uppercase text-xl" style={{ color: "var(--gold)" }}>
          🏆 Campeão: {sim.teams[comp.winner_id]?.teamName}
        </div>
      )}
    </div>
  );
}
