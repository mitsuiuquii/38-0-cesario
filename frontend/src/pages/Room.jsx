import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useRoomSocket } from "../lib/useRoomSocket";
import { FORMATION_KEYS } from "../lib/formations";
import Pitch from "../components/Pitch";
import { toast } from "sonner";

export default function Room() {
  const { code } = useParams();
  const nav = useNavigate();
  const playerId = localStorage.getItem(`38-0:pid:${code}`);
  const { state } = useRoomSocket(code, playerId);
  const [editName, setEditName] = useState("");
  const [stars, setStars] = useState(0);

  useEffect(() => {
    if (!playerId) nav("/");
  }, [playerId, nav]);

  useEffect(() => {
  if (state?.status === "drafting") nav(`/draft/${code}`);
  if (state?.status === "ready_to_sim" || state?.status === "simulating") nav(`/simulation/${code}`); // <-- Altere aqui também
  if (state?.status === "finished") nav(`/simulation/${code}`);
}, [state?.status, code, nav]);

  const myTeam = useMemo(
    () => state?.teams?.find((t) => t.id === playerId),
    [state, playerId]
  );
  const isHost = state?.hostId === playerId;

  useEffect(() => {
    if (myTeam && !editName) {
      const base = myTeam.teamName.replace(/[\s⭐]+$/, "");
      setEditName(base);
    }
  }, [myTeam?.teamName]);  // eslint-disable-line

  const saveName = async () => {
    const final = editName + (stars > 0 ? " " + "⭐".repeat(stars) : "");
    await api.updateTeam(code, { playerId, teamName: final });
  };

  const setFormation = async (formation) => {
    await api.updateTeam(code, { playerId, formation });
  };

  const toggleOvr = async () => {
    await api.hostUpdate(code, { playerId, showOvr: !state.showOvr });
  };

  const startDraft = async () => {
    try {
      await api.startDraft(code, playerId);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao iniciar");
    }
  };

  const copyCode = () => {
    navigator.clipboard.writeText(code);
    toast.success(`Código ${code} copiado!`);
  };

  if (!state) {
    return (
      <div className="relative z-10 min-h-screen flex items-center justify-center">
        <div className="font-oswald uppercase tracking-widest text-slate-400">Conectando à sala...</div>
      </div>
    );
  }

  return (
    <div className="relative z-10 min-h-screen px-4 md:px-10 py-8">
      <header className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <div className="font-anton text-2xl" style={{ color: "var(--neon)" }}>38—0</div>
          <span className="font-oswald uppercase tracking-widest text-xs text-slate-400">Sala de espera</span>
        </div>
        <button
          onClick={copyCode}
          className="glass px-4 py-2 hover:bg-white/10 transition"
          data-testid="room-copy-code-button"
        >
          <span className="text-xs font-oswald uppercase tracking-wider text-slate-400 mr-2">Código</span>
          <span className="font-anton text-2xl tracking-[0.3em]" style={{ color: "var(--gold)" }}>{code}</span>
        </button>
      </header>

      <div className="grid lg:grid-cols-[1fr_320px] gap-8">
        {/* Players list */}
        <div className="glass p-6">
          <h2 className="font-anton uppercase text-2xl tracking-wide mb-2">Convocados ({state.teams.length})</h2>
          <p className="text-slate-400 text-sm mb-5">
            Compartilhe o código <strong className="text-white">{code}</strong>
            {state.hasPassword && " (com a senha)"} para os amigos entrarem.
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            {state.teams.map((t) => (
              <div
                key={t.id}
                className={`glass p-4 ${t.id === playerId ? "border-[var(--neon)] border" : ""}`}
                data-testid={`room-team-${t.id}`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-oswald uppercase tracking-wider text-xs text-slate-400">
                    {t.id === state.hostId ? "Anfitrião" : "Jogador"}
                  </div>
                  <div className="font-oswald text-xs text-slate-400">{t.formation}</div>
                </div>
                <div className="font-anton text-2xl uppercase mt-1 truncate">{t.teamName}</div>
                <div className="text-slate-400 text-sm">{t.name}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Side panel: my team settings */}
        <aside className="space-y-6">
          <div className="glass p-5">
            <h3 className="font-anton uppercase text-xl mb-3">Seu Time</h3>
            <label className="text-xs font-oswald uppercase text-slate-400">Nome do time</label>
            <div className="flex gap-2 mt-1">
              <input
                className="input-base"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onBlur={saveName}
                maxLength={40}
                data-testid="room-team-name-input"
              />
              <button
                type="button"
                className="btn-ghost px-3"
                onClick={() => { setStars((s) => (s + 1) % 9); }}
                data-testid="room-star-button"
              >
                ⭐+{stars}
              </button>
            </div>
            <button className="btn-ghost mt-2 w-full" onClick={saveName} data-testid="room-save-name-button">
              Salvar
            </button>

            <div className="mt-5">
              <div className="text-xs font-oswald uppercase text-slate-400 mb-2">Formação</div>
              <div className="grid grid-cols-2 gap-2">
                {FORMATION_KEYS.map((f) => (
                  <button
                    key={f}
                    onClick={() => setFormation(f)}
                    className={`py-3 rounded-md font-anton text-lg border transition ${
                      myTeam?.formation === f
                        ? "border-[var(--neon)] bg-[var(--neon)]/10 text-[var(--neon)]"
                        : "border-white/10 text-slate-300 hover:border-white/40"
                    }`}
                    data-testid={`room-formation-${f}`}
                  >
                    {f}
                  </button>
                ))}
              </div>
            </div>

            {myTeam && (
              <div className="mt-5">
                <div className="text-xs font-oswald uppercase text-slate-400 mb-2">Preview do campo</div>
                <Pitch formation={myTeam.formation} squad={myTeam.squad} size="sm" />
              </div>
            )}
          </div>

          {isHost && (
            <div className="glass p-5">
              <h3 className="font-anton uppercase text-xl mb-3">Anfitrião</h3>
              <label className="flex items-center gap-3 text-sm text-slate-200">
                <input
                  type="checkbox"
                  className="w-4 h-4 accent-[var(--neon)]"
                  checked={state.showOvr}
                  onChange={toggleOvr}
                  data-testid="room-host-showovr-toggle"
                />
                Mostrar OVR dos adversários
              </label>
              <button
                className="btn-neon w-full mt-5"
                onClick={startDraft}
                disabled={state.teams.length < 2}
                data-testid="room-start-draft-button"
              >
                {state.teams.length < 2 ? "Aguardando jogadores..." : "Iniciar Draft"}
              </button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
