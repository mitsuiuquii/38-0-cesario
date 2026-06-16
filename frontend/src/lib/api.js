import axios from "axios";

export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";
export const API = `${BACKEND_URL}/api`;

export const wsUrl = (code, playerId) => {
  const wsBase = BACKEND_URL.replace(/^http/, "ws");
  return `${wsBase}/api/ws/${code}?playerId=${encodeURIComponent(playerId || "")}`;
};

const c = axios.create({ baseURL: API });

export const api = {
  createRoom: (data) => c.post("/rooms", data).then((r) => r.data),
  joinRoom: (code, data) => c.post(`/rooms/${code}/join`, data).then((r) => r.data),
  getRoom: (code, playerId) =>
    c.get(`/rooms/${code}`, { params: { playerId } }).then((r) => r.data),
  updateTeam: (code, data) => c.post(`/rooms/${code}/update-team`, data).then((r) => r.data),
  hostUpdate: (code, data) => c.post(`/rooms/${code}/host-update`, data).then((r) => r.data),
  startDraft: (code, playerId) =>
    c.post(`/rooms/${code}/start-draft`, { playerId }).then((r) => r.data),
  draftPick: (code, data) => c.post(`/rooms/${code}/draft-pick`, data).then((r) => r.data),
  startSim: (code, playerId) =>
    c.post(`/rooms/${code}/start-sim`, { playerId }).then((r) => r.data),
  setSpeed: (code, playerId, speed) =>
    c.post(`/rooms/${code}/set-speed`, { playerId, speed }).then((r) => r.data),
  nextRound: (code, playerId) =>
    c.post(`/rooms/${code}/next-round`, { playerId }).then((r) => r.data),
  restart: (code, playerId) =>
    c.post(`/rooms/${code}/restart`, { playerId }).then((r) => r.data),
  getFormations: () => c.get("/formations").then((r) => r.data),
};
