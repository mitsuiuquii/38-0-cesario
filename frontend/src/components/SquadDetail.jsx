import React from "react";
import { FORMATIONS } from "../lib/formations";

/** Read-only view of a team's full squad on a pitch (no OVR). */
export default function SquadDetail({ team, hideOvr = true }) {
  if (!team) return null;
  const formation = team.formation || "4-3-3";
  const slots = FORMATIONS[formation] || [];
  return (
    <div className="glass p-5">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <div className="font-anton uppercase text-2xl">{team.teamName}</div>
          <div className="text-xs font-oswald uppercase tracking-widest text-slate-400">
            {team.name ? team.name + " • " : ""}{formation}
          </div>
        </div>
      </div>
      <ul className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {slots.map((slot) => {
          const p = team.squad?.[slot.id];
          return (
            <li
              key={slot.id}
              className="flex items-center justify-between gap-2 bg-white/[0.04] border border-white/5 rounded-md px-2 py-1.5"
              data-testid={`squad-detail-${team.id}-${slot.id}`}
            >
              <span className="font-oswald text-[10px] uppercase tracking-wider text-slate-400 w-9">
                {slot.pos}
              </span>
              <span className="font-anton text-sm uppercase truncate flex-1">
                {p?.name || "—"}
              </span>
              {!hideOvr && p?.ovr !== undefined && (
                <span className="font-oswald text-xs text-[var(--neon)]">{p.ovr}</span>
              )}
            </li>
          );
        })}
      </ul>
      {team.squad && (
        <div className="mt-2 text-[10px] font-oswald uppercase tracking-widest text-slate-500">
          Era do elenco: {Array.from(new Set(Object.values(team.squad).filter(Boolean).map((p) => p.squad_label))).slice(0, 4).join(" • ")}
        </div>
      )}
    </div>
  );
}
