import React from "react";

const zoneClass = (idx) => {
  if (idx < 6) return "zone-libertadores";
  if (idx < 12) return "zone-sudamericana";
  if (idx >= 16) return "zone-rebaixamento";
  return "";
};

export default function StandingsTable({ standings = [], myTeamId, compact = false }) {
  const sorted = [...standings].sort((a, b) =>
    b.Pts - a.Pts || b.GD - a.GD || b.GF - a.GF || a.teamName.localeCompare(b.teamName)
  );
  return (
    <div className="glass overflow-hidden" data-testid="standings-table">
      <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
        <h3 className="font-anton text-xl tracking-wider uppercase">Classificação</h3>
        <div className="flex gap-3 text-[10px] font-oswald uppercase">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{background:"var(--green-zone)"}} /> Libertadores</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{background:"var(--blue-zone)"}} /> Sul-Americana</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{background:"var(--red-zone)"}} /> Rebaixamento</span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm font-outfit">
          <thead className="text-[10px] uppercase font-oswald text-slate-400 bg-black/30">
            <tr>
              <th className="px-2 py-2 text-left">#</th>
              <th className="px-2 py-2 text-left">Time</th>
              <th className="px-2 py-2 text-center">P</th>
              <th className="px-2 py-2 text-center">V</th>
              <th className="px-2 py-2 text-center">E</th>
              <th className="px-2 py-2 text-center">D</th>
              {!compact && <th className="px-2 py-2 text-center">GP</th>}
              {!compact && <th className="px-2 py-2 text-center">GC</th>}
              <th className="px-2 py-2 text-center">SG</th>
              <th className="px-2 py-2 text-center font-bold text-white">Pts</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, idx) => {
              const isMe = row.id === myTeamId;
              return (
                <tr
                  key={row.id}
                  className={`${zoneClass(idx)} ${isMe ? "bg-white/10" : ""}
                    border-b border-white/5 hover:bg-white/[0.04]`}
                  data-testid={`standings-row-${row.id}`}
                >
                  <td className="px-2 py-2 font-oswald text-slate-300">{idx + 1}</td>
                  <td className="px-2 py-2 truncate max-w-[160px]">
                    <span className={`${isMe ? "text-[var(--neon)] font-semibold" : ""}`}>
                      {row.teamName}
                    </span>
                    {row.isNpc && (
                      <span className="ml-2 text-[9px] uppercase text-slate-500 tracking-widest">CPU</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-center font-oswald">{row.P}</td>
                  <td className="px-2 py-2 text-center font-oswald">{row.W}</td>
                  <td className="px-2 py-2 text-center font-oswald">{row.D}</td>
                  <td className="px-2 py-2 text-center font-oswald">{row.L}</td>
                  {!compact && <td className="px-2 py-2 text-center font-oswald">{row.GF}</td>}
                  {!compact && <td className="px-2 py-2 text-center font-oswald">{row.GA}</td>}
                  <td className="px-2 py-2 text-center font-oswald">
                    {row.GD > 0 ? `+${row.GD}` : row.GD}
                  </td>
                  <td className="px-2 py-2 text-center font-anton text-base">{row.Pts}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
