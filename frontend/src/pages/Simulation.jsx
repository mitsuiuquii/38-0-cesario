import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useRoomSocket } from "../lib/useRoomSocket";
import StandingsTable from "../components/StandingsTable";
import { toast } from "sonner";

const SPEEDS = [
  { id: "slow", label: "Lento (90s)" },
  { id: "fast", label: "Rápido (20s)" },
  { id: "turbo", label: "Turbo (5s)" },
];

export default function Simulation() {
  const { code } = useParams();
  const nav = useNavigate();
  const playerId = localStorage.getItem(`38-0:pid:${code}`);

  const [minute, setMinute] = useState(0);
  const [matches, setMatches] = useState([]);
  const [flashIdx, setFlashIdx] = useState(null);
  const [goalFeed, setGoalFeed] = useState([]);
  const flashTimer = useRef(null);
  const [history, setHistory] = useState([]);

  const handleEvent = (msg) => {
    if (msg.type === "round_start") {
      setMinute(0);
      setMatches(msg.payload.matches.map((m) => ({ ...m, currentEvents: [] })));
      setGoalFeed([]);
    } else if (msg.type === "tick") {
      setMinute(msg.payload.minute);
      setMatches((prev) =>
        prev.map((m, idx) => {
          const tickEv = msg.payload.events.filter((e) => e.match_idx === idx);
          const [hs, as_] = msg.payload.scores[idx] || [m.home_score, m.away_score];
          return { ...m, home_score: hs, away_score: as_,
                   currentEvents: [...(m.currentEvents || []), ...tickEv.map((e) => e.event)] };
        })
      );
      // flash + goal feed for goals only
      msg.payload.events.forEach((e) => {
        if (e.event && !e.event.flavor) {
          setFlashIdx(e.match_idx);
          clearTimeout(flashTimer.current);
          flashTimer.current = setTimeout(() => setFlashIdx(null), 1300);
          setGoalFeed((prev) =>
            [
              {
                key: `${e.match_idx}-${e.event.minute}-${Math.random()}`,
                minute: e.event.minute,
                scorer: e.event.scorer,
                match_idx: e.match_idx,
              },
              ...prev,
            ].slice(0, 30)
          );
        }
      });
    } else if (msg.type === "round_end") {
      setHistory(msg.payload.history);
    } else if (msg.type === "sim_complete") {
      toast.success("Temporada finalizada!");
    }
  };

  const { state } = useRoomSocket(code, playerId, handleEvent);

  useEffect(() => {
    if (!playerId) nav("/");
  }, [playerId, nav]);

  // If room is ready_to_sim and I'm host, show "start" button. If simulating, show live screen.
  const isHost = state?.hostId === playerId;
  const status = state?.status;

  const startSim = async () => {
    try {
      await api.startSim(code, playerId);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao iniciar simulação");
    }
  };
  const changeSpeed = async (s) => {
    try {
      await api.setSpeed(code, playerId, s);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao alterar velocidade");
    }
  };

  const standings = useMemo(() => {
    if (!state?.league?.standings) return [];
    return Object.values(state.league.standings);
  }, [state?.league?.standings]);

  const champion = useMemo(() => {
    if (status !== "finished" || !standings.length) return null;
    return [...standings].sort((a, b) =>
      b.Pts - a.Pts || b.GD - a.GD || b.GF - a.GF
    )[0];
  }, [status, standings]);

  if (!state) {
    return (
      <div className="relative z-10 min-h-screen flex items-center justify-center">
        <div className="font-oswald uppercase tracking-widest text-slate-400">Carregando...</div>
      </div>
    );
  }

  if (status === "ready_to_sim") {
    return (
      <div className="relative z-10 min-h-screen flex flex-col items-center justify-center px-6 py-10">
        <div className="font-oswald uppercase tracking-widest text-slate-400 mb-3">Draft finalizado</div>
        <h1 className="font-anton uppercase text-5xl md:text-7xl text-center mb-3">Hora da Bola Rolar</h1>
        <p className="text-slate-300 max-w-xl text-center mb-7">
          Todos os times foram montados. A IA vai completar o campeonato com {20 - state.teams.length} esquadrões
          históricos como adversários. 38 rodadas até o título.
        </p>
        <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-3 max-w-3xl w-full mb-8">
          {state.teams.map((t) => (
            <div key={t.id} className="glass p-4">
              <div className="font-anton uppercase text-lg truncate">{t.teamName}</div>
              <div className="text-xs font-oswald uppercase text-slate-400">
                {t.formation} • OVR {t.ovr}
              </div>
            </div>
          ))}
        </div>
        {isHost ? (
          <button className="btn-neon" onClick={startSim} data-testid="sim-start-button">
            Iniciar Temporada
          </button>
        ) : (
          <div className="font-oswald uppercase tracking-widest text-slate-400">
            Aguardando o anfitrião apertar o play...
          </div>
        )}
      </div>
    );
  }

  if (status === "finished" && champion) {
    return (
      <div className="relative z-10 min-h-screen px-4 md:px-10 py-10">
        <div className="text-center mb-10">
          <div className="font-oswald uppercase tracking-[0.4em] text-slate-400 text-xs mb-2">Temporada Encerrada</div>
          <h1 className="font-anton uppercase leading-none" style={{ fontSize: "clamp(48px, 8vw, 120px)" }}>
            CAMPEÃO
          </h1>
          <div className="mt-4 inline-block glass px-8 py-6">
            <div className="font-anton uppercase text-5xl" style={{ color: "var(--gold)" }}>
              {champion.teamName}
            </div>
            <div className="font-oswald text-slate-400 mt-1 tracking-wider">
              {champion.Pts} pts • {champion.W}V {champion.D}E {champion.L}D • Saldo {champion.GD > 0 ? "+" : ""}{champion.GD}
            </div>
          </div>
        </div>
        <StandingsTable standings={standings} myTeamId={playerId} />
      </div>
    );
  }

  const league = state.league;
  const round = league?.currentRound || 0;
  const totalRounds = league?.totalRounds || 38;

  return (
    <div className="relative z-10 min-h-screen px-3 md:px-8 py-6">
      <header className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="font-anton text-2xl" style={{ color: "var(--neon)" }}>38—0</div>
          <span className="font-oswald uppercase tracking-widest text-xs text-slate-400">Simulação ao vivo</span>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">Rodada</div>
            <div className="font-anton text-3xl" data-testid="sim-current-round">
              {round}<span className="text-slate-500">/{totalRounds}</span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">Tempo</div>
            <div className="font-anton text-3xl">
              {minute}<span className="minute-pulse" style={{color:"var(--neon)"}}>{"'"}</span>
            </div>
          </div>
          {isHost && (
            <div className="flex gap-1 glass p-1 rounded-full">
              {SPEEDS.map((s) => (
                <button
                  key={s.id}
                  onClick={() => changeSpeed(s.id)}
                  className={`text-[10px] font-oswald uppercase tracking-wider px-3 py-2 rounded-full transition ${
                    state.speed === s.id
                      ? "bg-[var(--neon)] text-black"
                      : "text-slate-300 hover:text-white"
                  }`}
                  data-testid={`sim-speed-${s.id}`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      <div className="grid lg:grid-cols-[1fr_360px] gap-6">
        <div className="space-y-3">
          {/* Matches */}
          <div className="grid sm:grid-cols-2 gap-3">
            {matches.map((m, idx) => {
              const isMine = m.home_id === playerId || m.away_id === playerId;
              return (
                <div
                  key={`${m.home_id}-${m.away_id}-${idx}`}
                  className={`glass p-4 ${flashIdx === idx ? "goal-flash" : ""}
                    ${isMine ? "border-[var(--neon)] border" : ""}`}
                  data-testid={`match-card-${idx}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="font-oswald uppercase tracking-wider text-xs text-slate-400">
                        Mandante
                      </div>
                      <div className="font-anton uppercase text-lg truncate" title={m.home_name}>
                        {m.home_name}
                      </div>
                    </div>
                    <div className="text-center px-3">
                      <div className="font-anton text-3xl">
                        {m.home_score}<span className="text-slate-500 mx-1">×</span>{m.away_score}
                      </div>
                      {minute >= 90 ? (
                        <div className="text-[10px] font-oswald uppercase tracking-wider text-slate-400">Encerrado</div>
                      ) : (
                        <div className="flex items-center justify-center gap-1 text-[10px] font-oswald uppercase text-slate-400">
                          <span className="live-dot" /> {minute}{"'"}
                        </div>
                      )}
                    </div>
                    <div className="flex-1 text-right min-w-0">
                      <div className="font-oswald uppercase tracking-wider text-xs text-slate-400">
                        Visitante
                      </div>
                      <div className="font-anton uppercase text-lg truncate" title={m.away_name}>
                        {m.away_name}
                      </div>
                    </div>
                  </div>
                  {/* Last 2 events */}
                  <div className="mt-2 text-xs font-oswald text-slate-300 space-y-0.5">
                    {(m.currentEvents || []).slice(-2).map((ev, i) => (
                      <div key={i}>
                        {ev.flavor ? (
                          <span className="text-slate-500">
                            {ev.minute}{"'"} {ev.flavor === "yellow" ? "🟨 amarelo" :
                              ev.flavor === "save" ? "🧤 defesa" : "💨 quase!"}
                          </span>
                        ) : (
                          <span className="text-[var(--neon)]">
                            {ev.minute}{"'"} ⚽ {ev.scorer}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          <StandingsTable standings={standings} myTeamId={playerId} />
        </div>

        {/* Side: goal feed */}
        <aside className="glass p-4 h-fit lg:sticky lg:top-4">
          <h3 className="font-anton uppercase text-xl mb-3">Mural de Gols</h3>
          <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
            {goalFeed.length === 0 && (
              <div className="text-slate-500 text-sm">Nenhum gol ainda nesta rodada.</div>
            )}
            {goalFeed.map((g) => (
              <div key={g.key} className="flex items-center gap-2 text-sm font-oswald">
                <span className="font-anton text-[var(--neon)] w-10">{g.minute}{"'"}</span>
                <span>⚽ {g.scorer}</span>
              </div>
            ))}
          </div>
          {history.length > 0 && (
            <div className="mt-5 pt-4 border-t border-white/5">
              <div className="text-xs font-oswald uppercase tracking-widest text-slate-400 mb-2">Última rodada concluída</div>
              <div className="space-y-1 text-xs font-oswald">
                {history[history.length - 1]?.matches.map((m, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <span className="truncate flex-1">{m.home_name}</span>
                    <span className="font-anton mx-2">{m.home_score}-{m.away_score}</span>
                    <span className="truncate flex-1 text-right">{m.away_name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
