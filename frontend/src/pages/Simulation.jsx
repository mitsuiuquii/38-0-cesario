import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useRoomSocket } from "../lib/useRoomSocket";
import StandingsTable from "../components/StandingsTable";
import GroupStandings from "../components/GroupStandings";
import CupBracket from "../components/CupBracket";
import SquadDetail from "../components/SquadDetail";
import { toast } from "sonner";

const SPEEDS = [
  { id: "slow", label: "Lento (90s)" },
  { id: "fast", label: "Rápido (20s)" },
  { id: "turbo", label: "Turbo (5s)" },
];

const COMP_LABELS = {
  league: "Brasileirão",
  copa_brasil: "Copa do Brasil",
  libertadores: "Libertadores",
  sulamericana: "Sul-Americana",
};

export default function Simulation() {
  const { code } = useParams();
  const nav = useNavigate();
  const playerId = localStorage.getItem(`38-0:pid:${code}`);

  const [minute, setMinute] = useState(0);
  const [matches, setMatches] = useState([]);
  const [flashIdx, setFlashIdx] = useState(null);
  const [goalFeed, setGoalFeed] = useState([]);
  const [activeTab, setActiveTab] = useState("league"); // Já existente
  const [showSquads, setShowSquads] = useState(false); // Já existente
  const [localStatus, setLocalStatus] = useState(null); // <--- ADICIONE ESTA LINHA
  const flashTimer = useRef(null);

  const handleEvent = (msg) => {
    if (msg.type === "round_start") {
      setMinute(0);
      setMatches(msg.payload.matches.map((m) => ({ ...m, currentEvents: [] })));
      setGoalFeed([]);
      // auto-focus the active tab
      if (msg.payload.comp_id) setActiveTab(msg.payload.comp_id);
    } else if (msg.type === "tick") {
  setMinute(msg.payload.minute);
  setMatches((prev) =>
    prev.map((m, idx) => {
      const tickEv = msg.payload.events.filter((e) => e.matchIdx === idx);
      let hs = m.home_score;
      let as_ = m.away_score;
      if (tickEv.length > 0) {
        hs = tickEv[tickEv.length - 1].home_score ?? hs;
        as_ = tickEv[tickEv.length - 1].away_score ?? as_;
      }
      return {
        ...m,
        home_score: hs,
        away_score: as_,
        currentEvents: [...(m.currentEvents || []), ...tickEv.map((e) => e.event)],
      };
    })
  );
  msg.payload.events.forEach((e) => {
    if (e.event && !e.event.flavor) {
      setFlashIdx(e.matchIdx);
      clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => setFlashIdx(null), 1300);
      setGoalFeed((prev) =>
        [
          {
            key: `${e.matchIdx}-${e.event.minute}-${Math.random()}`,
            minute: e.event.minute,
            scorer: e.event.player_name,
          },
          ...prev,
        ].slice(0, 30)
      );
    }
  });
} else if (msg.type === "sim_complete") {
      toast.success("Temporada finalizada!");
    }
  };

  const { state } = useRoomSocket(code, playerId, handleEvent);

  useEffect(() => {
    if (!playerId) nav("/");
  }, [playerId, nav]);

  const isHost = state?.hostId === playerId;
  const status = localStatus || state?.status;
  const sim = state?.sim;
  const activeComp = sim?.competitions?.[activeTab];
  const activeRunningCompId = sim?.active;
  const runningComp = sim?.competitions?.[activeRunningCompId];
  const compStatus = runningComp?.status || "ready";
  const isPlaying = compStatus === "playing";

  // When the active running comp changes, sync the tab to it
  useEffect(() => {
    if (sim?.active && sim.active !== "completed") {
      setActiveTab(sim.active);
    }
  }, [sim?.active]);

  // Nova função para buscar os dados direto do banco de dados se o socket cair
  const fetchCurrentRoom = async () => {
    try {
      // Faz uma requisição GET para trazer a sala atualizada com as partidas criadas
      const response = await api.getRoom(code); 
      if (response?.data?.sim) {
        // Se a sua API retornar a estrutura da simulação, você pode forçar as partidas na tela:
        const activeCompId = response.data.sim.active || "league";
        setActiveTab(activeCompId);
        
        const currentComp = response.data.sim.competitions?.[activeCompId];
        const currentPhaseIdx = currentComp?.currentPhaseIdx ?? 0;
        if (currentComp?.phases?.[currentPhaseIdx]?.matches) {
          setMatches(currentComp.phases[currentPhaseIdx].matches);
        }
      }
    } catch (e) {
      console.error("Erro ao buscar dados de segurança da sala:", e);
    }
  };

  // Efeito para disparar a busca caso o status mude para simulando
  useEffect(() => {
    if (status === "simulating") {
      fetchCurrentRoom();
    }
  }, [status]);

  const startSim = async () => {
    try {
      await api.startSim(code, playerId);
      
      // 1. Força o status local para mudar a tela visualmente na hora
      setLocalStatus("simulating"); 
      
      // 2. Busca as partidas criadas direto da API (banco de dados)
      await fetchCurrentRoom(); 
      
      toast.success("Temporada iniciada!");
    } catch (e) {
      // Se der erro 400 porque já está rodando, faz a mesma coisa para destravar a tela
      if (e.response?.status === 400) {
        setLocalStatus("simulating");
        await fetchCurrentRoom();
        return;
      }
      toast.error(e.response?.data?.detail || "Erro ao iniciar simulação");
    }
  };

  const nextRound = async () => {
    try {
      await api.nextRound(code, playerId);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao avançar");
    }
  };

  const changeSpeed = async (s) => {
    try {
      await api.setSpeed(code, playerId, s);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao alterar velocidade");
    }
  };
  const restart = async () => {
    try {
      await api.restart(code, playerId);
      nav(`/sala/${code}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao reiniciar");
    }
  };

  const standingsList = useMemo(() => {
    if (!activeComp?.standings) return [];
    return Object.values(activeComp.standings);
  }, [activeComp?.standings]);

  if (!state) {
    return (
      <div className="relative z-10 min-h-screen flex items-center justify-center">
        <div className="font-oswald uppercase tracking-widest text-slate-400">Carregando...</div>
      </div>
    );
  }

  // -------------------- READY TO SIM SCREEN --------------------
  if (status === "ready_to_sim") {
    return (
      <div className="relative z-10 min-h-screen flex flex-col items-center justify-center px-6 py-10">
        <div className="font-oswald uppercase tracking-widest text-slate-400 mb-3">Draft finalizado</div>
        <h1 className="font-anton uppercase text-5xl md:text-7xl text-center mb-3">Hora da Bola Rolar</h1>
        <p className="text-slate-300 max-w-xl text-center mb-7">
          Todos os times foram montados. Vão rolar 4 competições nessa temporada:
          Brasileirão Série A, Copa do Brasil, Libertadores e Sul-Americana.
        </p>
        <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-3 max-w-3xl w-full mb-8">
          {state.teams.map((t) => (
            <div key={t.id} className="glass p-4">
              <div className="font-anton uppercase text-lg truncate">{t.teamName}</div>
              <div className="text-xs font-oswald uppercase text-slate-400">
                {t.formation}{t.id === playerId && t.ovr ? ` • OVR ${t.ovr}` : ""}
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

  // -------------------- FINISHED SCREEN --------------------
  if (status === "finished") {
    const trophies = ["league", "copa_brasil", "libertadores", "sulamericana"]
      .map((id) => sim?.competitions?.[id])
      .filter((c) => c?.winner_id);
    return (
      <div className="relative z-10 min-h-screen px-4 md:px-10 py-10">
        <div className="text-center mb-10">
          <div className="font-oswald uppercase tracking-[0.4em] text-slate-400 text-xs mb-2">
            Temporada Encerrada
          </div>
          <h1 className="font-anton uppercase leading-none" style={{ fontSize: "clamp(48px, 8vw, 120px)" }}>
            CAMPEÕES
          </h1>
        </div>
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4 max-w-6xl mx-auto mb-10">
          {trophies.map((c) => (
            <div key={c.id} className="glass p-5 text-center" data-testid={`trophy-${c.id}`}>
              <div className="text-3xl mb-2">🏆</div>
              <div className="text-xs font-oswald uppercase tracking-widest text-slate-400">{c.name}</div>
              <div className="font-anton uppercase text-2xl mt-1" style={{ color: "var(--gold)" }}>
                {sim.teams[c.winner_id]?.teamName}
              </div>
            </div>
          ))}
        </div>

        <div className="max-w-6xl mx-auto space-y-6">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <h2 className="font-anton uppercase text-3xl">Resumo</h2>
            <div className="flex gap-3">
              <button
                className="btn-ghost"
                onClick={() => setShowSquads((s) => !s)}
                data-testid="finished-show-squads-button"
              >
                {showSquads ? "Ocultar Elencos" : "Ver Elencos"}
              </button>
              {isHost && (
                <button
                  className="btn-neon"
                  onClick={restart}
                  data-testid="finished-replay-button"
                >
                  Jogar Novamente
                </button>
              )}
            </div>
          </div>

          {showSquads && (
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
              {state.teams.map((t) => (
                <SquadDetail key={t.id} team={t} hideOvr={true} />
              ))}
            </div>
          )}

          <StandingsTable
            standings={Object.values(sim?.competitions?.league?.standings || {})}
            myTeamId={playerId}
          />
        </div>
      </div>
    );
  }

  // -------------------- LIVE SIMULATION SCREEN --------------------
  const phasesPlayed = (activeComp?.currentPhaseIdx ?? -1) + (compStatus === "playing" ? 0 : 1);
  const totalPhases = activeComp?.phases?.length || 0;
  const currentPhaseName = activeComp?.phases?.[activeComp?.currentPhaseIdx]?.name;

  return (
    <div className="relative z-10 min-h-screen px-3 md:px-8 py-6">
      <header className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="font-anton text-2xl" style={{ color: "var(--neon)" }}>38—0</div>
          <span className="font-oswald uppercase tracking-widest text-xs text-slate-400">
            Simulação ao vivo
          </span>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <div className="text-right">
            <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">Fase</div>
            <div className="font-anton text-xl truncate max-w-[180px]" data-testid="sim-current-phase">
              {currentPhaseName || "—"}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">Tempo</div>
            <div className="font-anton text-3xl">
              {minute}<span className="minute-pulse" style={{ color: "var(--neon)" }}>{"'"}</span>
            </div>
          </div>
          {isHost && (
            <div className="flex gap-1 glass p-1 rounded-full">
              {SPEEDS.map((s) => (
                <button
                  key={s.id}
                  onClick={() => changeSpeed(s.id)}
                  className={`text-[10px] font-oswald uppercase tracking-wider px-3 py-2 rounded-full transition ${
                    state.speed === s.id ? "bg-[var(--neon)] text-black" : "text-slate-300 hover:text-white"
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

      {/* Competition tabs */}
      <div className="glass p-1.5 mb-4 inline-flex flex-wrap gap-1">
        {["league", "copa_brasil", "libertadores", "sulamericana"].map((cid) => {
          const c = sim?.competitions?.[cid];
          const isAvail = !!c;
          const isActive = activeTab === cid;
          return (
            <button
              key={cid}
              disabled={!isAvail}
              onClick={() => setActiveTab(cid)}
              className={`text-xs font-oswald uppercase tracking-widest px-4 py-2 rounded-full transition ${
                isActive ? "bg-[var(--neon)] text-black" : "text-slate-300 hover:text-white"
              } ${!isAvail ? "opacity-40 cursor-not-allowed" : ""}`}
              data-testid={`tab-${cid}`}
            >
              {COMP_LABELS[cid]}
              {c?.status === "completed" && c.winner_id && (
                <span className="ml-2">🏆</span>
              )}
            </button>
          );
        })}
      </div>

      {/* Active competition content */}
      <div className="grid lg:grid-cols-[1fr_360px] gap-6">
        <div className="space-y-4">
          {/* Phase bar */}
          {activeComp && (
            <div className="glass px-4 py-3 flex items-center justify-between flex-wrap gap-3">
              <div>
                <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">
                  {activeComp.name}
                </div>
                <div className="font-anton uppercase text-2xl">
                  {phasesPlayed}/{totalPhases || "?"} fases
                </div>
              </div>
              {/* Next round button */}
              {isHost && activeTab === activeRunningCompId && compStatus !== "playing" &&
                runningComp && runningComp.status !== "completed" && (
                  <button
                    className="btn-neon"
                    onClick={nextRound}
                    data-testid="sim-next-round-button"
                  >
                    {compStatus === "ready" ? "Iniciar 1ª Rodada" : "Próxima Rodada"}
                  </button>
                )}
              {isPlaying && (
                <div className="flex items-center gap-2 text-xs font-oswald uppercase tracking-widest text-slate-300">
                  <span className="live-dot" /> Rodada em andamento
                </div>
              )}
            </div>
          )}

          {/* When this tab is the active running competition show live matches */}
          {activeTab === activeRunningCompId && matches.length > 0 && (
            <div className="grid sm:grid-cols-2 gap-3" data-testid="sim-live-matches">
              {matches.map((m, idx) => {
                const isMine = m.home_id === playerId || m.away_id === playerId;
                return (
                  <div
                    key={`${m.home_id}-${m.away_id}-${idx}`}
                    className={`glass p-4 ${flashIdx === idx ? "goal-flash" : ""} ${isMine ? "border-[var(--neon)] border" : ""}`}
                    data-testid={`match-card-${idx}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="font-oswald uppercase tracking-wider text-xs text-slate-400">
                          {m.neutral ? "Neutro" : "Mandante"}
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
                          <div className="text-[10px] font-oswald uppercase tracking-wider text-slate-400">
                            Encerrado
                          </div>
                        ) : (
                          <div className="flex items-center justify-center gap-1 text-[10px] font-oswald uppercase text-slate-400">
                            <span className="live-dot" /> {minute}{"'"}
                          </div>
                        )}
                        {m.leg && (
                          <div className="text-[9px] font-oswald uppercase tracking-widest text-slate-500 mt-0.5">
                            Jogo {m.leg}
                          </div>
                        )}
                      </div>
                      <div className="flex-1 text-right min-w-0">
                        <div className="font-oswald uppercase tracking-wider text-xs text-slate-400">
                          {m.neutral ? "Neutro" : "Visitante"}
                        </div>
                        <div className="font-anton uppercase text-lg truncate" title={m.away_name}>
                          {m.away_name}
                        </div>
                      </div>
                    </div>
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
          )}

          {/* Standings / Bracket per competition */}
          {activeComp?.type === "league" && (
            <StandingsTable standings={standingsList} myTeamId={playerId} />
          )}
          {activeComp?.type === "groups_knockout" && (
            <>
              <GroupStandings comp={activeComp} sim={sim} myTeamId={playerId} />
              {activeComp.phases.length > 3 && (
                <CupBracket
                  comp={{
                    ...activeComp,
                    bracket: {
                      stages: activeComp.phases.slice(3).map((ph) => ({
                        name: ph.name,
                        matchups: ph.matches.map((m) => [m.home_id, m.away_id, m.tie_id]),
                      })),
                    },
                  }}
                  sim={sim}
                  myTeamId={playerId}
                />
              )}
            </>
          )}
          {activeComp?.type === "knockout" && (
            <CupBracket
              comp={{
                ...activeComp,
                bracket: {
                  stages: activeComp.phases.map((ph) => ({
                    name: ph.name,
                    matchups: ph.matches.map((m) => [m.home_id, m.away_id, m.tie_id]),
                  })),
                },
              }}
              sim={sim}
              myTeamId={playerId}
            />
          )}
        </div>

        {/* Side panel: goal feed */}
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
          {isHost && (
            <div className="mt-5 pt-4 border-t border-white/5">
              <button
                className="btn-ghost w-full text-xs"
                onClick={() => {
                  if (window.confirm("Reiniciar a sala? O draft recomeçará com os mesmos jogadores.")) {
                    restart();
                  }
                }}
                data-testid="sim-restart-button"
              >
                Reiniciar Sala
              </button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
