import React from "react";
import { FORMATIONS, ovrTint } from "../lib/formations";

/**
 * Pitch — top-down field that renders all 11 slots for the given formation.
 * If a slot has a player, render player card; if empty, render the slot label.
 * Optional callbacks: onSlotClick(slotId), highlightSlots set of slotIds for valid targets.
 */
export default function Pitch({
  formation = "4-3-3",
  squad = {},
  onSlotClick,
  highlightSlots = new Set(),
  invalidSlots = new Set(),
  showOvr = true,
  size = "md",
}) {
  const slots = FORMATIONS[formation] || FORMATIONS["4-3-3"];
  const containerClass =
    size === "sm" ? "max-w-[280px]" : size === "lg" ? "max-w-[520px]" : "max-w-[420px]";

  return (
    <div className={`${containerClass} mx-auto w-full`}>
      <div className="pitch pitch-lines" data-testid="pitch-visualizer">
        <div className="pitch-box-top">
          <div className="pitch-spot" style={{ top: "70%" }} />
        </div>
        <div className="pitch-box-bot">
          <div className="pitch-spot" style={{ top: "30%" }} />
        </div>
        {slots.map((slot) => {
          const player = squad[slot.id];
          const isTarget = highlightSlots.has(slot.id);
          const isInvalid = invalidSlots.has(slot.id);
          return (
            <div
              key={slot.id}
              className="player-slot"
              style={{ left: `${slot.x}%`, top: `${slot.y}%` }}
              data-testid={`pitch-slot-${slot.id}`}
            >
              {player ? (
                <div
                  className="pcard"
                  onClick={() => onSlotClick && onSlotClick(slot.id)}
                  data-testid={`pitch-player-${slot.id}`}
                >
                  <div className={`pcard-ovr ${ovrTint(showOvr ? player.ovr : null)}`}>
                    {showOvr && player.ovr !== undefined ? player.ovr : "?"}
                    <div className="pcard-pos">{slot.pos}</div>
                  </div>
                  <div className="pcard-name" title={player.name}>{player.name}</div>
                </div>
              ) : (
                <div
                  className={`slot-empty ${isTarget ? "slot-target" : ""} ${
                    isInvalid ? "slot-invalid" : ""
                  }`}
                  onClick={() => onSlotClick && onSlotClick(slot.id)}
                  data-testid={`pitch-empty-${slot.id}`}
                >
                  {slot.pos}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
