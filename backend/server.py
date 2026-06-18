"""38-0 Brasil — FastAPI backend with WebSocket realtime sync.

Supports:
  • Multi-competition season: Brasileirão Série A, Copa do Brasil,
    Copa Libertadores, Copa Sul-Americana (sequential, all sharing
    the drafted human teams + a shared NPC pool).
  • Round-by-round (host clicks "Próxima Rodada" between phases).
  • Strict player uniqueness by NAME across all eras / squads.
  • No duplicate club-year squad in the same league (humans + NPCs).
  • Play-again: reset the room back to lobby, keep the players.
"""
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, List
from dotenv import load_dotenv
from pathlib import Path
import os
import asyncio
import logging
import random
import string
import time
import uuid

from squads import SQUADS, all_players_flat, all_squad_labels, get_squad_by_label
from match_engine import (
    FORMATIONS, slot_accepts_player, simulate_match_goals,
    team_ovr, generate_fixtures, pick_random_npc_squad,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("38-0")

app = FastAPI(title="38-0 Cesario Match Simulator API")
api = APIRouter(prefix="/api")

# ----------------------------- Models -----------------------------
class CreateRoomInput(BaseModel):
    name: str
    password: Optional[str] = None

class JoinRoomInput(BaseModel):
    name: str
    password: Optional[str] = None

class UpdateTeamInput(BaseModel):
    playerId: str
    teamName: Optional[str] = None
    formation: Optional[str] = None

class HostUpdateInput(BaseModel):
    playerId: str
    showOvr: bool

class StartDraftInput(BaseModel):
    playerId: str

class DraftPickInput(BaseModel):
    playerId: str
    playerUid: str
    slotIndex: int

class StartSimInput(BaseModel):
    playerId: str

class SetSpeedInput(BaseModel):
    playerId: str
    speed: float

class NextRoundInput(BaseModel):
    playerId: str

class RestartInput(BaseModel):
    playerId: str

# ----------------------------- State -----------------------------
ROOMS: Dict[str, dict] = {}
WS_CONNS: Dict[str, List[WebSocket]] = {}

def generate_room_code(length=5) -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=length))
        if code not in ROOMS:
            return code

def public_room(room: dict, current_player_id: Optional[str] = None) -> dict:
    return {
        "code": room["code"],
        "hostId": room["hostId"],
        "status": room["status"],
        "hasPassword": room["password"] is not None and room["password"] != "",
        "showOvr": room["showOvr"],
        "teams": [
            {
                "id": t["id"],
                "name": t["name"],
                "teamName": t["teamName"],
                "formation": t["formation"],
                "squad": t["squad"] if room["showOvr"] or t["id"] == current_player_id else [
                    {**p, "ovr": 0} if p else None for p in t["squad"]
                ]
            }
            for t in room["teams"]
        ],
        "availablePlayers": room["availablePlayers"],
        "draftState": room["draftState"],
        "fixtures": room["fixtures"],
        "standings": room["standings"],
        "currentRound": room["currentRound"],
        "totalRounds": room["totalRounds"],
        "speed": room["speed"],
        "competition": room["competition"],
        "history": room["history"],
    }

async def broadcast(code: str, msg_type: str):
    if code not in ROOMS or code not in WS_CONNS:
        return
    payload = ROOMS[code]
    for ws in list(WS_CONNS[code]):
        try:
            pid = getattr(ws, "_player_id", None)
            await ws.send_json({"type": msg_type, "payload": public_room(payload, pid)})
        except Exception:
            try:
                WS_CONNS[code].remove(ws)
            except ValueError:
                pass

# ----------------------------- API Routes -----------------------------
@api.post("/rooms")
def create_room(inp: CreateRoomInput):
    code = generate_room_code()
    pid = str(uuid.uuid4())
    ROOMS[code] = {
        "code": code,
        "hostId": pid,
        "password": inp.password if inp.password else None,
        "status": "lobby",
        "showOvr": True,
        "teams": [{
            "id": pid,
            "name": inp.name,
            "teamName": f"Time de {inp.name}",
            "formation": "4-3-3",
            "squad": [None] * 11
        }],
        "availablePlayers": [],
        "draftState": {"currentTurn": 0, "pickingPlayerId": None, "direction": 1},
        "fixtures": [],
        "standings": [],
        "currentRound": 0,
        "totalRounds": 0,
        "speed": 1.0,
        "sim": None,
        "competition": "Brasileirão Série A",
        "history": [],
    }
    return {"code": code, "playerId": pid}

@api.post("/rooms/{code}/join")
def join_room(code: str, inp: JoinRoomInput):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    if room["status"] != "lobby":
        raise HTTPException(status_code=400, detail="Jogo já iniciou")
    if room["password"] and room["password"] != inp.password:
        raise HTTPException(status_code=401, detail="Senha incorreta")
    if len(room["teams"]) >= 20:
        raise HTTPException(status_code=400, detail="Sala cheia (máx 20)")
    for t in room["teams"]:
        if t["name"].lower() == inp.name.lower():
            raise HTTPException(status_code=400, detail="Nome já em uso nesta sala")
    pid = str(uuid.uuid4())
    room["teams"].append({
        "id": pid,
        "name": inp.name,
        "teamName": f"Time de {inp.name}",
        "formation": "4-3-3",
        "squad": [None] * 11
    })
    asyncio.create_task(broadcast(code, "state"))
    return {"code": code, "playerId": pid}

@api.get("/rooms/{code}")
def get_room(code: str, playerId: Optional[str] = None):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    return public_room(ROOMS[code], playerId)

@api.post("/rooms/{code}/update-team")
async def update_team(code: str, inp: UpdateTeamInput):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    team = next((t for t in room["teams"] if t["id"] == inp.playerId), None)
    if not team:
        raise HTTPException(status_code=404, detail="Jogador não na sala")
    if inp.teamName is not None:
        team["teamName"] = inp.teamName.strip()
    if inp.formation is not None:
        if inp.formation not in FORMATIONS:
            raise HTTPException(status_code=400, detail="Formação inválida")
        team["formation"] = inp.formation
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/host-update")
async def host_update(code: str, inp: HostUpdateInput):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    if room["hostId"] != inp.playerId:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião")
    room["showOvr"] = inp.showOvr
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/start-draft")
async def start_draft(code: str, inp: StartDraftInput):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    if room["hostId"] != inp.playerId:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião")
    if len(room["teams"]) < 2:
        raise HTTPException(status_code=400, detail="Mínimo 2 jogadores")
    if room["status"] != "lobby":
         raise HTTPException(status_code=400, detail="Não está em lobby")
    used_names = {t["teamName"].lower() for t in room["teams"]}
    if len(used_names) < len(room["teams"]):
        raise HTTPException(status_code=400, detail="Nomes de times duplicados")
    random.shuffle(room["teams"])
    room["availablePlayers"] = list(all_players_flat)
    room["status"] = "drafting"
    room["draftState"] = {
        "currentTurn": 0,
        "pickingPlayerId": room["teams"][0]["id"],
        "direction": 1
    }
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/draft-pick")
async def draft_pick(code: str, inp: DraftPickInput):
    code = code.upper()
    if code not in ROOMS:
         raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    if room["status"] != "drafting":
         raise HTTPException(status_code=400, detail="Não está em fase de draft")
    ds = room["draftState"]
    if ds["pickingPlayerId"] != inp.playerId:
         raise HTTPException(status_code=403, detail="Não é seu turno")
    team = next((t for t in room["teams"] if t["id"] == inp.playerId), None)
    if not team:
         raise HTTPException(status_code=404, detail="Time não encontrado")
    if inp.slotIndex < 0 or inp.slotIndex >= 11:
         raise HTTPException(status_code=400, detail="Slot inválido")
    if team["squad"][inp.slotIndex] is not None:
         raise HTTPException(status_code=400, detail="Slot já ocupado")
    p_obj = next((p for p in room["availablePlayers"] if p["uid"] == inp.playerUid), None)
    if not p_obj:
         raise HTTPException(status_code=404, detail="Jogador indisponível")
    allowed = slot_accepts_player(team["formation"], inp.slotIndex, p_obj["pos"])
    if not allowed:
         raise HTTPException(status_code=400, detail="Posição incompatível com o slot")
    team["squad"][inp.slotIndex] = p_obj
    room["availablePlayers"] = [p for p in room["availablePlayers"] if p["uid"] != inp.playerUid]
    num_humans = len(room["teams"])
    total_slots = num_humans * 11
    ds["currentTurn"] += 1
    curr = ds["currentTurn"]
    if curr >= total_slots:
        room["status"] = "ready_to_sim"
        room["currentRound"] = 1
        room["history"] = []
        npc_needed = 20 - num_humans
        if npc_needed < 0:
            npc_needed = 0
        used_labels = {t["teamName"] for t in room["teams"]}
        for _ in range(npc_needed):
            lbl = pick_random_npc_squad(used_labels)
            used_labels.add(lbl)
            sq = get_squad_by_label(lbl)
            room["teams"].append({
                "id": f"npc_{str(uuid.uuid4())[:8]}",
                "name": f"[NPC] {lbl}",
                "teamName": lbl,
                "formation": sq["formation"],
                "squad": sq["players"]
            })
        room["competition"] = "Brasileirão Série A"
        room["fixtures"] = generate_fixtures(room["teams"])
        room["totalRounds"] = len(room["fixtures"])
        room["standings"] = [{"teamName": t["teamName"], "p": 0, "j": 0, "v": 0, "e": 0, "d": 0, "gp": 0, "gc": 0, "sg": 0, "isNpc": t["id"].startswith("npc_")} for t in room["teams"]]
        room["draftState"] = {"currentTurn": curr, "pickingPlayerId": None, "direction": 1}
        await broadcast(code, "state")
        return {"ok": True}
    round_index = curr // num_humans
    intra_index = curr % num_humans
    if round_index % 2 == 1:
        idx = (num_humans - 1) - intra_index
    else:
        idx = intra_index
    ds["pickingPlayerId"] = room["teams"][idx]["id"]
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/start-sim")
async def start_sim(code: str, inp: StartSimInput):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    if room["hostId"] != inp.playerId:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião")
    if room["status"] != "ready_to_sim":
        raise HTTPException(status_code=400, detail="Não está pronto para simular")
    room["status"] = "simulating"
    sim = MatchSimulator(room)
    room["sim"] = sim
    asyncio.create_task(sim.run_loop())
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/set-speed")
async def set_speed(code: str, inp: SetSpeedInput):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    if room["hostId"] != inp.playerId:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião")
    room["speed"] = max(0.1, min(inp.speed, 5.0))
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/next-round")
async def next_round(code: str, inp: NextRoundInput):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    if room["hostId"] != inp.playerId:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião")
    if room["status"] != "ready_to_sim":
        raise HTTPException(status_code=400, detail="A rodada atual não terminou")
    if room["currentRound"] >= room["totalRounds"]:
        current_comp = room["competition"]
        room["history"].append({
            "competition": current_comp,
            "standings": list(room["standings"])
        })
        next_map = {
            "Brasileirão Série A": "Copa do Brasil",
            "Copa do Brasil": "Copa Libertadores",
            "Copa Libertadores": "Copa Sul-Americana",
            "Copa Sul-Americana": "finished"
        }
        nxt = next_map.get(current_comp, "finished")
        if nxt == "finished":
            room["status"] = "finished"
            await broadcast(code, "state")
            return {"ok": True}
        room["competition"] = nxt
        room["fixtures"] = generate_fixtures(room["teams"])
        room["currentRound"] = 1
        room["totalRounds"] = len(room["fixtures"])
        room["standings"] = [{"teamName": t["teamName"], "p": 0, "j": 0, "v": 0, "e": 0, "d": 0, "gp": 0, "gc": 0, "sg": 0, "isNpc": t["id"].startswith("npc_")} for t in room["teams"]]
        room["status"] = "ready_to_sim"
        await broadcast(code, "state")
        return {"ok": True}
    room["currentRound"] += 1
    room["status"] = "ready_to_sim"
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/restart")
async def restart(code: str, inp: RestartInput):
    code = code.upper()
    if code not in ROOMS:
        raise HTTPException(status_code=404, detail="Sala não encontrada")
    room = ROOMS[code]
    if room["hostId"] != inp.playerId:
        raise HTTPException(status_code=403, detail="Apenas o anfitrião")
    room["status"] = "lobby"
    room["teams"] = [t for t in room["teams"] if not t["id"].startswith("npc_")]
    for t in room["teams"]:
        t["squad"] = [None] * 11
    room["fixtures"] = []
    room["standings"] = []
    room["currentRound"] = 0
    room["totalRounds"] = 0
    room["history"] = []
    room["availablePlayers"] = []
    room["sim"] = None
    await broadcast(code, "state")
    return {"ok": True}


# ----------------------------- WebSocket -----------------------------
@app.websocket("/api/ws/{code}")
async def ws_endpoint(ws: WebSocket, code: str, playerId: Optional[str] = None):
    code = code.upper()
    await ws.accept()
    if code not in ROOMS:
        await ws.send_json({"type": "error", "payload": {"msg": "Sala não encontrada"}})
        await ws.close()
        return
    ws._player_id = playerId
    WS_CONNS.setdefault(code, []).append(ws)
    try:
        await ws.send_json({"type": "state", "payload": public_room(ROOMS[code], playerId)})
        while True:
            data = await ws.receive_json()
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"WS error {code}: {e}")
    finally:
        try:
            WS_CONNS[code].remove(ws)
        except ValueError:
            pass


# ----------------------------- Mount + CORS -----------------------------
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://38-0-cesarioo.vercel.app",  # Seu link de produção da Vercel
        "http://localhost:3000",             # Seu link local
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)