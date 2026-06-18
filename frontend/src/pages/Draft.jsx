import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useRoomSocket } from "../lib/useRoomSocket";
import Pitch from "../components/Pitch";
import { ovrTint } from "../lib/formations";
import { toast } from "sonner";

export default function Draft() {
  const { code } = useParams();
  const nav = useNavigate();
  const playerId = localStorage.getItem(`38-0:pid:${code}`);
  const { state, lastEvent } = useRoomSocket(code, playerId);
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [picking, setPicking] = useState(false);

  useEffect(() => {
    if (!playerId) nav("/");
  }, [playerId, nav]);

  useEffect(() => {
  if (state?.status === "ready_to_sim" || state?.status === "simulating" || state?.status === "finished") {
    nav(`/jogo/${code}`); // <--- Volte para /jogo/
  }
}, [state?.status, code, nav]);

  // Toast when our turn starts
  const isMyTurn = useMemo(() => {
    if (!state || !state.draftOrder?.length) return false;
    const idx = state.draftOrder[state.currentTurnIdx];
    return state.teams[idx]?.id === playerId;
  }, [state, playerId]);

  useEffect(() => {
    if (isMyTurn) {
      toast.success("É a sua vez!", { duration: 1800 });
    }
  }, [isMyTurn]);

  if (!state) {
    return (
      <div className="relative z-10 min-h-screen flex items-center justify-center">
        <div className="font-oswald uppercase tracking-widest text-slate-400">Carregando draft...</div>
      </div>
    );
  }

  const currentTeam = state.teams[state.draftOrder[state.currentTurnIdx]];
  const myTeam = state.teams.find((t) => t.id === playerId);

  const validSlotsForCard = (card) => new Set(card?.valid_slots || []);

  const pick = async (card) => {
    if (!isMyTurn) {
      toast.error("Não é a sua vez");
      return;
    }
    let slot = selectedSlot;
    if (!slot) {
      // Auto-pick first valid slot
      slot = card.valid_slots[0];
    }
    if (!card.valid_slots.includes(slot)) {
      toast.error(`Esse jogador não joga em ${slot}`);
      return;
    }
    setPicking(true);
    try {
      await api.draftPick(code, { playerId, cardId: card.id, slotId: slot });
      setSelectedSlot(null);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao escolher");
    } finally {
      setPicking(false);
    }
  };

  const totalPicks = state.teams.length * 11;
  const pickedSoFar = state.teams.reduce(
    (acc, t) => acc + Object.values(t.squad).filter((p) => p).length,
    0
  );
  const pickProgress = Math.round((pickedSoFar / totalPicks) * 100);

  return (
    <div className="relative z-10 min-h-screen px-4 md:px-8 py-6">
      <header className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="font-anton text-2xl" style={{ color: "var(--neon)" }}>38—0</div>
          <span className="font-oswald uppercase tracking-widest text-xs text-slate-400">Draft em andamento</span>
        </div>
        <div className="text-right">
          <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">Progresso</div>
          <div className="font-anton text-2xl">{pickedSoFar} / {totalPicks}</div>
        </div>
      </header>

      {/* Turn banner */}
      <div
        className={`glass mb-5 px-5 py-4 flex items-center justify-between ${
          isMyTurn ? "border-[var(--neon)] border" : ""
        }`}
        style={isMyTurn ? { boxShadow: "0 0 28px rgba(57,255,20,0.25)" } : {}}
        data-testid="draft-turn-banner"
      >
        <div>
          <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">
            {isMyTurn ? "É a sua vez de escolher" : "Vez de"}
          </div>
          <div className="font-anton uppercase text-3xl">
            {isMyTurn ? "ESCOLHA UM JOGADOR" : currentTeam?.teamName}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] font-oswald uppercase tracking-widest text-slate-400">Clube sorteado</div>
          <div className="font-anton uppercase text-2xl" style={{ color: "var(--gold)" }}>
            {state.assignedClub}
          </div>
        </div>
      </div>

      {/* progress bar */}
      <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden mb-6">
        <div
          className="h-full"
          style={{ width: `${pickProgress}%`, background: "var(--neon)", transition: "width 0.4s ease" }}
        />
      </div>

      <div className="grid lg:grid-cols-[1fr_460px_300px] gap-6">
        {/* Left: available player cards */}
        <section>
          <h2 className="font-anton uppercase text-xl mb-3">Jogadores disponíveis</h2>
          {!isMyTurn && (
            <div className="text-slate-400 text-sm mb-3">
              Aguarde sua vez. A lista será atualizada quando o draft chegar até você.
            </div>
          )}
          <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-3 max-h-[70vh] overflow-y-auto pr-1">
            {(state.availablePlayers || []).map((card) => (
              <button
                key={card.id}
                onClick={() => pick(card)}
                disabled={!isMyTurn || picking}
                className="glass p-3 text-left hover:bg-white/[0.06] transition group disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid={`draft-card-${card.id}`}
              >
                <div className="flex items-start justify-between">
                  <div className={`pcard-ovr ${ovrTint(card.ovr)} px-2 rounded-md`}>
                    <span className="font-anton text-2xl">{card.ovr}</span>
                  </div>
                  <div className="flex flex-wrap gap-1 justify-end max-w-[120px]">
                    {card.positions.map((p) => (
                      <span key={p} className="text-[10px] font-oswald uppercase tracking-wider px-1.5 py-0.5 rounded bg-white/10">
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="font-anton uppercase text-lg leading-tight mt-2 truncate">{card.name}</div>
                <div className="text-xs font-oswald text-slate-400 uppercase tracking-wider">{card.squad_label}</div>
                {isMyTurn && (
                  <div className="mt-2 text-[10px] font-oswald uppercase tracking-wider text-[var(--neon)]">
                    Encaixa em: {card.valid_slots.join(", ")}
                  </div>
                )}
              </button>
            ))}
            {isMyTurn && (state.availablePlayers || []).length === 0 && (
              <div className="col-span-full text-slate-400 text-sm">
                Nenhum jogador deste clube cabe no seu time agora — o sistema sorteou outro clube automaticamente.
              </div>
            )}
          </div>
        </section>

        {/* Middle: pitch */}
        <section>
          <h2 className="font-anton uppercase text-xl mb-3 text-center">
            {myTeam?.teamName}
            <span className="ml-3 text-base text-slate-400">({myTeam?.formation})</span>
          </h2>
          {myTeam && (
            <Pitch
              formation={myTeam.formation}
              squad={myTeam.squad}
              size="md"
              showOvr={true}
              onSlotClick={(slotId) => setSelectedSlot(slotId === selectedSlot ? null : slotId)}
              highlightSlots={new Set(selectedSlot ? [selectedSlot] : [])}
            />
          )}
          {selectedSlot && (
            <div className="mt-3 text-center text-sm font-oswald text-[var(--neon)]">
              Slot selecionado: <strong>{selectedSlot}</strong> — clique num jogador compatível
            </div>
          )}
        </section>

        {/* Right: other teams */}
        <section className="space-y-3 max-h-[80vh] overflow-y-auto pr-1">
          <h2 className="font-anton uppercase text-xl mb-1">Sala</h2>
          {state.teams.map((t, idx) => {
            const turnIdx = state.draftOrder[state.currentTurnIdx];
            const isActive = state.teams[turnIdx]?.id === t.id;
            const filledCount = Object.values(t.squad).filter((p) => p).length;
            return (
              <div
                key={t.id}
                className={`glass p-3 ${isActive ? "border-[var(--neon)] border" : ""}`}
                data-testid={`draft-side-team-${t.id}`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-anton uppercase text-lg truncate max-w-[180px]">{t.teamName}</div>
                  {isActive && <div className="live-dot" />}
                </div>
                <div className="text-[10px] font-oswald uppercase tracking-wider text-slate-400">
                  {t.formation} • {filledCount}/11
                  {(state.showOvr || t.id === playerId) && t.ovr > 0 && (
                    <span className="ml-2 text-white">OVR {t.ovr}</span>
                  )}
                </div>
              </div>
            );
          })}
          <div className="text-[10px] font-oswald uppercase text-slate-500 mt-2">
            Ordem do snake: round {state.pickRound + 1}
          </div>
        </section>
      </div>
    </div>
  );
}
