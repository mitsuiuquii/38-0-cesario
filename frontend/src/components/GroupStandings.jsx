import React from "react";

const ZONE_BY_COMP = {
  league: (idx) => {
    if (idx < 6) return "zone-libertadores";
    if (idx < 12) return "zone-sudamericana";
    if (idx >= 16) return "zone-rebaixamento";
    return "";
  },
  default: () => "",
};

/** Group standings table (for Libertadores / Sul-Americana). Top 2 of each group highlighted. */
export default function GroupStandings({ comp, sim, myTeamId }) {
  if (!comp?.groups) return null;
  const standings = comp.standings;
  const groups = comp.groups;
  return (
    <div className="grid sm:grid-cols-2 gap-4">
      {Object.entries(groups).map(([groupName, ids]) => {
        const rows = ids
          .map((id) => standings[id])
          .sort((a, b) => b.Pts - a.Pts || b.GD - a.GD || b.GF - a.GF);
        return (
          <div key={groupName} className="glass overflow-hidden" data-testid={`group-${comp.id}-${groupName}`}>
            <div className="px-3 py-2 border-b border-white/5 font-anton uppercase">
              Grupo {groupName}
            </div>
            <table className="w-full text-xs font-oswald">
              <thead className="text-slate-400 bg-black/30">
                <tr>
                  <th className="px-2 py-1 text-left">#</th>
                  <th className="px-2 py-1 text-left">Time</th>
                  <th className="px-2 py-1 text-center">P</th>
                  <th className="px-2 py-1 text-center">V</th>
                  <th className="px-2 py-1 text-center">SG</th>
                  <th className="px-2 py-1 text-center">Pts</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, idx) => {
                  const isMe = r.id === myTeamId;
                  const isAdv = idx < 2;
                  return (
                    <tr
                      key={r.id}
                      className={`${isAdv ? "zone-libertadores" : ""} ${isMe ? "bg-white/10" : ""} border-b border-white/5`}
                    >
                      <td className="px-2 py-1">{idx + 1}</td>
                      <td className="px-2 py-1 truncate max-w-[140px]">
                        <span className={isMe ? "text-[var(--neon)] font-semibold" : ""}>
                          {r.teamName}
                        </span>
                        {r.country && r.country !== "BRA" && (
                          <span className="ml-1 text-[9px] text-slate-500">{r.country}</span>
                        )}
                      </td>
                      <td className="px-2 py-1 text-center">{r.P}</td>
                      <td className="px-2 py-1 text-center">{r.W}</td>
                      <td className="px-2 py-1 text-center">{r.GD > 0 ? `+${r.GD}` : r.GD}</td>
                      <td className="px-2 py-1 text-center font-anton">{r.Pts}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}

export { ZONE_BY_COMP };
