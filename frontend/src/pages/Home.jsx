import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { toast } from "sonner";

const Stars = ({ value }) => {
  if (!value) return null;
  return <span className="text-[var(--gold)]">{"★".repeat(Math.min(value, 8))}</span>;
};

export default function Home() {
  const nav = useNavigate();
  const [mode, setMode] = useState(null); // null | "create" | "join"
  const [name, setName] = useState("");
  const [teamName, setTeamName] = useState("");
  const [stars, setStars] = useState(0);
  const [password, setPassword] = useState("");
  const [showOvr, setShowOvr] = useState(true);
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);

  const finalTeamName = teamName + (stars > 0 ? " " + "⭐".repeat(stars) : "");

  const handleCreate = async () => {
    if (!name.trim() || !teamName.trim()) {
      toast.error("Preencha seu nome e o nome do time");
      return;
    }
    setLoading(true);
    try {
      const res = await api.createRoom({
        name: name.trim(),
        teamName: finalTeamName.trim(),
        password: password || null,
        showOvr,
      });
      localStorage.setItem("38-0:lastRoom", res.code);
      localStorage.setItem(`38-0:pid:${res.code}`, res.playerId);
      nav(`/sala/${res.code}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao criar sala");
    } finally {
      setLoading(false);
    }
  };

  const handleJoin = async () => {
    if (!name.trim() || !teamName.trim() || !code.trim()) {
      toast.error("Preencha todos os campos");
      return;
    }
    setLoading(true);
    try {
      const c = code.trim().toUpperCase();
      const res = await api.joinRoom(c, {
        name: name.trim(),
        teamName: finalTeamName.trim(),
        password: password || null,
      });
      localStorage.setItem(`38-0:pid:${c}`, res.playerId);
      nav(`/sala/${c}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao entrar na sala");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative z-10 min-h-screen flex flex-col">
      {/* HERO */}
      <header className="px-6 md:px-12 pt-10 pb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-md flex items-center justify-center font-anton text-xl"
              style={{ background: "linear-gradient(135deg, var(--neon), var(--gold))", color: "#06120B" }}
            >
              38
            </div>
            <span className="font-oswald uppercase tracking-[0.3em] text-sm text-slate-400">
              Brasileirão Draft Simulator
            </span>
          </div>
          <div className="hidden md:flex items-center gap-2 text-xs font-oswald uppercase tracking-widest text-slate-500">
            <span className="live-dot" /> ao vivo entre amigos
          </div>
        </div>
      </header>

      <section className="flex-1 flex items-center justify-center px-6 md:px-12">
        <div className="max-w-5xl w-full grid md:grid-cols-2 gap-10 items-center">
          <div>
            <h1
              className="font-anton uppercase leading-[0.92] tracking-tight"
              style={{ fontSize: "clamp(56px, 9vw, 128px)" }}
            >
              <span className="block text-white">38—0</span>
              <span className="block" style={{ color: "var(--neon)" }}>BRASIL</span>
            </h1>
            <p className="mt-5 text-slate-300 max-w-md font-outfit">
              Convoque os amigos, monte sua equipe com lendas dos times brasileiros e dispute
              uma temporada inteira do Brasileirão. <span className="text-white">Pelé, Romário, Zico, Ronaldinho</span>{" "}
              — todos disponíveis. Quem levanta a taça?
            </p>
            <div className="mt-8 grid grid-cols-3 gap-3 text-center">
              {[
                { k: "28", t: "Esquadrões Históricos" },
                { k: "390+", t: "Jogadores" },
                { k: "38", t: "Rodadas / Temporada" },
              ].map((it) => (
                <div key={it.t} className="glass px-3 py-4">
                  <div className="font-anton text-3xl" style={{ color: "var(--gold)" }}>{it.k}</div>
                  <div className="font-oswald text-[10px] uppercase tracking-wider text-slate-400 mt-1">{it.t}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Lobby card */}
          <div className="glass p-7 md:p-9" data-testid="lobby-card">
            {!mode && (
              <div className="flex flex-col gap-4">
                <h2 className="font-anton text-3xl uppercase tracking-wide">Como você joga hoje?</h2>
                <p className="text-slate-400 text-sm">Crie uma sala e mande o código pros amigos — ou entre numa que já existe.</p>
                <button
                  className="btn-neon w-full"
                  onClick={() => setMode("create")}
                  data-testid="home-create-room-button"
                >
                  Criar Sala
                </button>
                <button
                  className="btn-ghost w-full"
                  onClick={() => setMode("join")}
                  data-testid="home-join-room-button"
                >
                  Entrar com Código
                </button>
              </div>
            )}

            {mode && (
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                  <h2 className="font-anton text-2xl uppercase tracking-wide">
                    {mode === "create" ? "Criar Sala" : "Entrar na Sala"}
                  </h2>
                  <button
                    className="text-xs font-oswald uppercase tracking-wider text-slate-400 hover:text-white"
                    onClick={() => setMode(null)}
                    data-testid="home-back-button"
                  >
                    Voltar
                  </button>
                </div>

                <div>
                  <label className="text-xs font-oswald uppercase tracking-wider text-slate-400">Seu nome</label>
                  <input
                    className="input-base mt-1"
                    placeholder="ex: Tony"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    maxLength={24}
                    data-testid="home-name-input"
                  />
                </div>

                <div>
                  <label className="text-xs font-oswald uppercase tracking-wider text-slate-400">Nome do time</label>
                  <div className="flex gap-2 mt-1">
                    <input
                      className="input-base"
                      placeholder="ex: Caju FC"
                      value={teamName}
                      onChange={(e) => setTeamName(e.target.value)}
                      maxLength={40}
                      data-testid="home-team-input"
                    />
                    <button
                      type="button"
                      className="btn-ghost px-3"
                      onClick={() => setStars((s) => (s + 1) % 9)}
                      title="Adicionar título"
                      data-testid="home-star-button"
                    >
                      ⭐ +{stars}
                    </button>
                  </div>
                  {stars > 0 && (
                    <div className="mt-1 text-sm font-oswald text-slate-300">
                      {teamName} <Stars value={stars} />
                    </div>
                  )}
                </div>

                {mode === "join" && (
                  <div>
                    <label className="text-xs font-oswald uppercase tracking-wider text-slate-400">Código da sala</label>
                    <input
                      className="input-base mt-1 font-anton text-2xl tracking-[0.4em] uppercase"
                      placeholder="A3X9LM"
                      value={code}
                      onChange={(e) => setCode(e.target.value.toUpperCase())}
                      maxLength={6}
                      data-testid="home-code-input"
                    />
                  </div>
                )}

                <div>
                  <label className="text-xs font-oswald uppercase tracking-wider text-slate-400">Senha (opcional)</label>
                  <input
                    className="input-base mt-1"
                    placeholder="—"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    data-testid="home-password-input"
                  />
                </div>

                {mode === "create" && (
                  <label className="flex items-center gap-3 text-sm text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      className="w-4 h-4 accent-[var(--neon)]"
                      checked={showOvr}
                      onChange={(e) => setShowOvr(e.target.checked)}
                      data-testid="home-showovr-toggle"
                    />
                    Mostrar OVR dos times adversários durante o draft
                  </label>
                )}

                {mode === "create" ? (
                  <button
                    className="btn-neon w-full"
                    onClick={handleCreate}
                    disabled={loading}
                    data-testid="home-confirm-create-button"
                  >
                    {loading ? "Criando..." : "Criar Sala"}
                  </button>
                ) : (
                  <button
                    className="btn-neon w-full"
                    onClick={handleJoin}
                    disabled={loading}
                    data-testid="home-confirm-join-button"
                  >
                    {loading ? "Entrando..." : "Entrar"}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      <footer className="px-6 md:px-12 py-6 text-center text-xs font-oswald uppercase tracking-[0.3em] text-slate-600">
        Feito para quem ainda canta a marchinha da inconfidência mineira
      </footer>
    </div>
  );
}
