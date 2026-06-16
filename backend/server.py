"""38-0 Brasil — FastAPI backend with WebSocket realtime sync."""
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, HTTPException
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

app = FastAPI()
api = APIRouter(prefix="/api")

# ----------------------------- In-memory state -----------------------------
ROOMS: Dict[str, dict] = {}  # code -> room state
WS_CONNS: Dict[str, List[WebSocket]] = {}  # code -> list of sockets
SIM_TASKS: Dict[str, asyncio.Task] = {}

SPEED_MS = {"slow": 1000, "fast": 220, "turbo": 55}
LEAGUE_SIZE = 20  # padded with NPC teams


# ----------------------------- Helpers -----------------------------
def gen_room_code() -> str:
    while True:
        c = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if c not in ROOMS:
            return c


def new_player_id() -> str:
    return uuid.uuid4().hex[:12]


def public_room(room: dict, viewer_id: Optional[str] = None) -> dict:
    """Return a snapshot of room state safe for the client.
    Hides OVR if showOvr is False and viewer is not host (unless league phase)."""
    show_ovr = room["showOvr"] or room["status"] in ("simulating", "finished")
    teams_pub = []
    for t in room["teams"]:
        squad = {}
        for slot_id, p in t["squad"].items():
            if p is None:
                squad[slot_id] = None
            else:
                pub = {**p}
                if not show_ovr and viewer_id is not None and t["id"] != viewer_id:
                    pub.pop("ovr", None)
                squad[slot_id] = pub
        teams_pub.append({
            **t,
            "squad": squad,
            "ovr": round(team_ovr(t["squad"]), 1) if any(t["squad"].values()) else 0,
        })
    return {
        "code": room["code"],
        "hasPassword": bool(room["password"]),
        "hostId": room["hostId"],
        "showOvr": room["showOvr"],
        "status": room["status"],
        "teams": teams_pub,
        "draftOrder": room.get("draftOrder", []),
        "currentTurnIdx": room.get("currentTurnIdx", 0),
        "pickRound": room.get("pickRound", 0),
        "assignedClub": room.get("assignedClub"),
        "availablePlayers": room.get("availablePlayers", []),
        "draftedPlayerIds": list(room.get("draftedPlayerIds", set())),
        "league": room.get("league"),
        "speed": room.get("speed", "fast"),
    }


async def broadcast(code: str, kind: str = "state", payload: Optional[dict] = None):
    if code not in WS_CONNS:
        return
    msg = {"type": kind, "payload": payload or {}}
    if kind == "state":
        # send per-viewer state respecting OVR visibility
        for ws in list(WS_CONNS.get(code, [])):
            try:
                viewer_id = getattr(ws, "_player_id", None)
                await ws.send_json({"type": "state", "payload": public_room(ROOMS[code], viewer_id)})
            except Exception:
                pass
    else:
        for ws in list(WS_CONNS.get(code, [])):
            try:
                await ws.send_json(msg)
            except Exception:
                pass


def empty_squad(formation: str) -> dict:
    return {slot["id"]: None for slot in FORMATIONS[formation]}


def player_id_set_for_room(room: dict) -> set:
    s = set(room.get("draftedPlayerIds", set()))
    return s


def assign_random_club_for_turn(room: dict) -> str:
    """Pick a random club for the current picker. Must have at least one valid player
    for one of their open slots."""
    team = room["teams"][room["draftOrder"][room["currentTurnIdx"]]]
    open_slots = [s for sid, s in zip(team["squad"].keys(), FORMATIONS[team["formation"]])
                  if team["squad"][s["id"]] is None]
    drafted = room["draftedPlayerIds"]
    labels = list(all_squad_labels())
    random.shuffle(labels)
    for label in labels:
        squad = get_squad_by_label(label)
        for p in squad["players"]:
            pid = f"{squad['club']}-{squad['year']}-{p['name']}"
            if pid in drafted:
                continue
            for slot in open_slots:
                if slot_accepts_player(slot["pos"], p["pos"]):
                    return label
    return labels[0]  # fallback


def players_for_assigned_club(room: dict) -> List[dict]:
    label = room["assignedClub"]
    squad = get_squad_by_label(label)
    if not squad:
        return []
    team = room["teams"][room["draftOrder"][room["currentTurnIdx"]]]
    open_slots = [s for s in FORMATIONS[team["formation"]] if team["squad"][s["id"]] is None]
    out = []
    for p in squad["players"]:
        pid = f"{squad['club']}-{squad['year']}-{p['name']}"
        if pid in room["draftedPlayerIds"]:
            continue
        valid_slots = [s["id"] for s in open_slots if slot_accepts_player(s["pos"], p["pos"])]
        if not valid_slots:
            continue
        out.append({
            "id": pid, "name": p["name"], "positions": p["pos"], "ovr": p["ovr"],
            "club": squad["club"], "year": squad["year"], "squad_label": squad["label"],
            "color": squad["color"], "accent": squad["accent"],
            "valid_slots": valid_slots,
        })
    return out


def advance_turn(room: dict):
    """Move to next picker following snake order. End draft if all teams full."""
    n = len(room["teams"])
    total_picks = n * 11
    if room["picksMade"] >= total_picks:
        room["status"] = "ready_to_sim"
        room["assignedClub"] = None
        room["availablePlayers"] = []
        return

    room["currentTurnIdx"] += 1
    # Snake: at end of forward round, reverse; at end of reverse round, forward again.
    # We model this with: pickRound increments, direction flips, idx resets.
    if room["currentTurnIdx"] >= n:
        # finished current round
        room["pickRound"] += 1
        room["draftOrder"].reverse()
        room["currentTurnIdx"] = 0
    room["assignedClub"] = assign_random_club_for_turn(room)
    room["availablePlayers"] = players_for_assigned_club(room)


# ----------------------------- HTTP API -----------------------------
class CreateRoomReq(BaseModel):
    name: str
    teamName: str
    password: Optional[str] = None
    showOvr: bool = True


class JoinRoomReq(BaseModel):
    name: str
    teamName: str
    password: Optional[str] = None


class UpdateTeamReq(BaseModel):
    playerId: str
    teamName: Optional[str] = None
    formation: Optional[str] = None


class HostUpdateReq(BaseModel):
    playerId: str
    showOvr: Optional[bool] = None


class DraftPickReq(BaseModel):
    playerId: str
    cardId: str  # player db id selected
    slotId: str


class SpeedReq(BaseModel):
    playerId: str
    speed: str


@api.get("/")
async def root():
    return {"message": "38-0 Brasil API", "squads": len(SQUADS), "players": len(all_players_flat())}


@api.get("/formations")
async def get_formations():
    return FORMATIONS


@api.get("/squads")
async def list_squads():
    return [{"label": s["label"], "club": s["club"], "year": s["year"],
             "color": s["color"], "accent": s["accent"],
             "player_count": len(s["players"])} for s in SQUADS]


@api.post("/rooms")
async def create_room(req: CreateRoomReq):
    code = gen_room_code()
    host_id = new_player_id()
    room = {
        "code": code,
        "password": req.password or "",
        "hostId": host_id,
        "showOvr": req.showOvr,
        "status": "lobby",
        "teams": [{
            "id": host_id, "name": req.name, "teamName": req.teamName or req.name,
            "formation": "4-3-3", "squad": empty_squad("4-3-3"),
        }],
        "draftOrder": [],
        "currentTurnIdx": 0,
        "pickRound": 0,
        "picksMade": 0,
        "draftedPlayerIds": set(),
        "assignedClub": None,
        "availablePlayers": [],
        "speed": "fast",
        "league": None,
        "createdAt": time.time(),
    }
    ROOMS[code] = room
    return {"code": code, "playerId": host_id}


@api.post("/rooms/{code}/join")
async def join_room(code: str, req: JoinRoomReq):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if room["status"] != "lobby":
        raise HTTPException(400, "Draft já iniciado nesta sala")
    if room["password"] and req.password != room["password"]:
        raise HTTPException(403, "Senha incorreta")
    if len(room["teams"]) >= 12:
        raise HTTPException(400, "Sala cheia (máx 12)")
    pid = new_player_id()
    room["teams"].append({
        "id": pid, "name": req.name, "teamName": req.teamName or req.name,
        "formation": "4-3-3", "squad": empty_squad("4-3-3"),
    })
    await broadcast(code, "state")
    return {"code": code, "playerId": pid}


@api.post("/rooms/{code}/update-team")
async def update_team(code: str, req: UpdateTeamReq):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    team = next((t for t in room["teams"] if t["id"] == req.playerId), None)
    if not team:
        raise HTTPException(404, "Jogador não está nesta sala")
    if room["status"] != "lobby":
        raise HTTPException(400, "Não é possível alterar após o draft iniciar")
    if req.teamName is not None:
        team["teamName"] = req.teamName[:60]
    if req.formation is not None and req.formation in FORMATIONS:
        team["formation"] = req.formation
        team["squad"] = empty_squad(req.formation)
    await broadcast(code, "state")
    return {"ok": True}


@api.post("/rooms/{code}/host-update")
async def host_update(code: str, req: HostUpdateReq):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]:
        raise HTTPException(403, "Somente o anfitrião pode alterar")
    if req.showOvr is not None:
        room["showOvr"] = req.showOvr
    await broadcast(code, "state")
    return {"ok": True}


@api.post("/rooms/{code}/start-draft")
async def start_draft(code: str, req: HostUpdateReq):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]:
        raise HTTPException(403, "Somente o anfitrião pode iniciar")
    if room["status"] != "lobby":
        raise HTTPException(400, "Draft já iniciado")
    if len(room["teams"]) < 2:
        raise HTTPException(400, "Mínimo 2 jogadores para iniciar")
    # Randomize order (this defines snake forward direction)
    order_idx = list(range(len(room["teams"])))
    random.shuffle(order_idx)
    room["draftOrder"] = order_idx
    room["status"] = "drafting"
    room["currentTurnIdx"] = 0
    room["pickRound"] = 0
    room["picksMade"] = 0
    room["draftedPlayerIds"] = set()
    room["assignedClub"] = assign_random_club_for_turn(room)
    room["availablePlayers"] = players_for_assigned_club(room)
    await broadcast(code, "state")
    return {"ok": True}


@api.post("/rooms/{code}/draft-pick")
async def draft_pick(code: str, req: DraftPickReq):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if room["status"] != "drafting":
        raise HTTPException(400, "Draft não está em andamento")
    current_team_idx = room["draftOrder"][room["currentTurnIdx"]]
    team = room["teams"][current_team_idx]
    if team["id"] != req.playerId:
        raise HTTPException(403, "Não é a sua vez")
    if req.cardId in room["draftedPlayerIds"]:
        raise HTTPException(400, "Jogador já foi escolhido")
    # Find player in availablePlayers
    card = next((p for p in room["availablePlayers"] if p["id"] == req.cardId), None)
    if not card:
        raise HTTPException(400, "Jogador não disponível neste clube")
    if req.slotId not in card["valid_slots"]:
        raise HTTPException(400, "Posição inválida para este jogador")
    if team["squad"][req.slotId] is not None:
        raise HTTPException(400, "Posição já preenchida")
    # Place
    team["squad"][req.slotId] = {
        "id": card["id"], "name": card["name"], "ovr": card["ovr"],
        "positions": card["positions"], "squad_label": card["squad_label"],
        "color": card["color"], "accent": card["accent"],
    }
    room["draftedPlayerIds"].add(card["id"])
    room["picksMade"] += 1
    await broadcast(code, "pick", {"team_id": team["id"], "slotId": req.slotId,
                                   "card": team["squad"][req.slotId]})
    advance_turn(room)
    await broadcast(code, "state")
    return {"ok": True}


@api.post("/rooms/{code}/start-sim")
async def start_sim(code: str, req: HostUpdateReq):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]:
        raise HTTPException(403, "Somente o anfitrião pode iniciar")
    if room["status"] != "ready_to_sim":
        raise HTTPException(400, f"Estado inválido: {room['status']}")
    # Build league: human teams + NPC teams to fill to LEAGUE_SIZE
    league_teams = []
    for t in room["teams"]:
        league_teams.append({
            "id": t["id"], "teamName": t["teamName"], "isNpc": False,
            "ovr": round(team_ovr(t["squad"]), 1),
            "squad": t["squad"], "formation": t["formation"],
        })
    used_pids = set(room["draftedPlayerIds"])
    npc_idx = 0
    while len(league_teams) < LEAGUE_SIZE:
        # try to fill with a random squad as an NPC team
        labels = all_squad_labels()
        random.shuffle(labels)
        formation = random.choice(list(FORMATIONS.keys()))
        slots = FORMATIONS[formation]
        team_built = None
        for label in labels:
            squad = get_squad_by_label(label)
            built = pick_random_npc_squad(squad["players"], used_pids, slots)
            if built is None:
                continue
            # Need to namespace player ids
            for sid, p in built.items():
                pid_full = f"{squad['club']}-{squad['year']}-{p['name']}"
                used_pids.add(pid_full)
            team_built = {
                "id": f"npc_{npc_idx}",
                "teamName": f"{squad['label']} XI",
                "isNpc": True,
                "formation": formation,
                "squad": {sid: {"id": f"{squad['club']}-{squad['year']}-{p['name']}",
                                "name": p["name"], "ovr": p["ovr"], "positions": p["pos"],
                                "squad_label": squad["label"],
                                "color": squad["color"], "accent": squad["accent"]}
                          for sid, p in built.items()},
            }
            team_built["ovr"] = round(team_ovr(team_built["squad"]), 1)
            break
        if team_built is None:
            # Fallback: random pool team
            pool = [p for p in all_players_flat() if p["id"] not in used_pids]
            random.shuffle(pool)
            slot_objs = FORMATIONS["4-3-3"]
            sq = {}
            for slot in slot_objs:
                cand = next((p for p in pool if p["id"] not in used_pids and
                             slot_accepts_player(slot["pos"], p["positions"])), None)
                if cand:
                    used_pids.add(cand["id"])
                    sq[slot["id"]] = {"id": cand["id"], "name": cand["name"],
                                      "ovr": cand["ovr"], "positions": cand["positions"],
                                      "squad_label": cand["squad_label"],
                                      "color": cand["color"], "accent": cand["accent"]}
                else:
                    sq[slot["id"]] = {"id": f"unknown_{npc_idx}_{slot['id']}",
                                      "name": "Reserva", "ovr": 55,
                                      "positions": [slot["pos"]], "squad_label": "Mixto",
                                      "color": "#444", "accent": "#FFF"}
            team_built = {"id": f"npc_{npc_idx}", "teamName": f"Selecionado Histórico {npc_idx+1}",
                          "isNpc": True, "formation": "4-3-3", "squad": sq}
            team_built["ovr"] = round(team_ovr(team_built["squad"]), 1)
        league_teams.append(team_built)
        npc_idx += 1

    random.shuffle(league_teams)
    fixtures = generate_fixtures([t["id"] for t in league_teams])
    standings = {t["id"]: {"id": t["id"], "teamName": t["teamName"], "isNpc": t["isNpc"],
                            "ovr": t["ovr"], "P": 0, "W": 0, "D": 0, "L": 0,
                            "GF": 0, "GA": 0, "GD": 0, "Pts": 0} for t in league_teams}
    room["league"] = {
        "teams": {t["id"]: t for t in league_teams},
        "fixtures": fixtures,
        "standings": standings,
        "currentRound": 0,
        "totalRounds": len(fixtures),
        "currentMatches": [],
        "history": [],
        "currentMinute": 0,
        "finished": False,
    }
    room["status"] = "simulating"
    await broadcast(code, "state")
    # Launch sim task
    if code in SIM_TASKS and not SIM_TASKS[code].done():
        SIM_TASKS[code].cancel()
    SIM_TASKS[code] = asyncio.create_task(run_simulation(code))
    return {"ok": True}


@api.post("/rooms/{code}/set-speed")
async def set_speed(code: str, req: SpeedReq):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]:
        raise HTTPException(403, "Somente o anfitrião pode mudar a velocidade")
    if req.speed not in SPEED_MS:
        raise HTTPException(400, "Velocidade inválida")
    room["speed"] = req.speed
    await broadcast(code, "state")
    return {"ok": True}


@api.get("/rooms/{code}")
async def get_room(code: str, playerId: Optional[str] = None):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    return public_room(room, playerId)


# ----------------------------- Simulation Loop -----------------------------
async def run_simulation(code: str):
    """Run all 38 rounds, broadcasting tick/goal events for animated match clocks."""
    room = ROOMS[code]
    league = room["league"]
    try:
        for round_idx in range(league["totalRounds"]):
            league["currentRound"] = round_idx + 1
            league["currentMinute"] = 0
            # Pre-compute all matches in this round
            current_matches = []
            for (home_id, away_id) in league["fixtures"][round_idx]:
                ht = league["teams"][home_id]
                at = league["teams"][away_id]
                home_form = random.uniform(-5, 5)
                away_form = random.uniform(-5, 5)
                hg, ag, events = simulate_match_goals(ht["ovr"], at["ovr"], home_form, away_form)
                # Pre-determine scorers for goals based on player attacking weight
                def pick_scorer(team):
                    pool = []
                    for slot_id, p in team["squad"].items():
                        if p is None:
                            continue
                        # weight by position
                        weight = 1
                        pos = p.get("positions", [])
                        if any(x in pos for x in ["ST"]):
                            weight = 8
                        elif any(x in pos for x in ["LW", "RW", "CAM"]):
                            weight = 5
                        elif any(x in pos for x in ["CM", "LM", "RM"]):
                            weight = 3
                        elif any(x in pos for x in ["CB", "LB", "RB", "CDM"]):
                            weight = 1
                        elif "GK" in pos:
                            weight = 0
                        pool.extend([p] * weight)
                    return random.choice(pool) if pool else None

                final_events = []
                for ev in events:
                    if "flavor" not in ev:
                        scorer = pick_scorer(ht if ev["team"] == "home" else at)
                        final_events.append({**ev, "scorer": scorer["name"] if scorer else "?"})
                    else:
                        final_events.append(ev)
                current_matches.append({
                    "home_id": home_id, "away_id": away_id,
                    "home_name": ht["teamName"], "away_name": at["teamName"],
                    "home_color": next((p["color"] for p in ht["squad"].values() if p), "#222"),
                    "away_color": next((p["color"] for p in at["squad"].values() if p), "#222"),
                    "home_score": 0, "away_score": 0,
                    "final_home": hg, "final_away": ag,
                    "events": final_events,
                    "emitted": [],
                    "home_is_npc": ht["isNpc"], "away_is_npc": at["isNpc"],
                })
            league["currentMatches"] = current_matches
            await broadcast(code, "round_start", {"round": round_idx + 1,
                                                  "matches": current_matches})

            # Tick minute by minute
            for minute in range(1, 91):
                speed = room.get("speed", "fast")
                delay = SPEED_MS.get(speed, 220) / 1000.0
                await asyncio.sleep(delay)
                league["currentMinute"] = minute
                tick_events = []
                for m in current_matches:
                    fired = [e for e in m["events"] if e["minute"] == minute]
                    for ev in fired:
                        if "flavor" not in ev:
                            if ev["team"] == "home":
                                m["home_score"] += 1
                            else:
                                m["away_score"] += 1
                        m["emitted"].append(ev)
                        tick_events.append({"match_idx": current_matches.index(m), "event": ev,
                                            "home_id": m["home_id"], "away_id": m["away_id"]})
                await broadcast(code, "tick", {"minute": minute, "events": tick_events,
                                                "scores": [(m["home_score"], m["away_score"])
                                                           for m in current_matches]})

            # End of round — update standings
            for m in current_matches:
                hs = league["standings"][m["home_id"]]
                as_ = league["standings"][m["away_id"]]
                hg, ag = m["home_score"], m["away_score"]
                hs["P"] += 1
                as_["P"] += 1
                hs["GF"] += hg
                hs["GA"] += ag
                as_["GF"] += ag
                as_["GA"] += hg
                hs["GD"] = hs["GF"] - hs["GA"]
                as_["GD"] = as_["GF"] - as_["GA"]
                if hg > ag:
                    hs["W"] += 1
                    hs["Pts"] += 3
                    as_["L"] += 1
                elif ag > hg:
                    as_["W"] += 1
                    as_["Pts"] += 3
                    hs["L"] += 1
                else:
                    hs["D"] += 1
                    as_["D"] += 1
                    hs["Pts"] += 1
                    as_["Pts"] += 1
            league["history"].append({
                "round": round_idx + 1,
                "matches": [{"home_id": m["home_id"], "away_id": m["away_id"],
                              "home_name": m["home_name"], "away_name": m["away_name"],
                              "home_score": m["home_score"], "away_score": m["away_score"]}
                             for m in current_matches],
            })
            await broadcast(code, "round_end", {"round": round_idx + 1,
                                                "standings": list(league["standings"].values()),
                                                "history": league["history"]})
            # short pause between rounds
            await asyncio.sleep(0.7)

        league["finished"] = True
        room["status"] = "finished"
        await broadcast(code, "state")
        await broadcast(code, "sim_complete", {"standings": list(league["standings"].values())})
    except asyncio.CancelledError:
        log.info(f"Simulation {code} cancelled")
    except Exception as e:
        log.exception(f"Simulation {code} failed: {e}")


# ----------------------------- WebSocket -----------------------------
@app.websocket("/api/ws/{code}")
async def ws_endpoint(ws: WebSocket, code: str, playerId: Optional[str] = None):
    code = code.upper()
    await ws.accept()
    if code not in ROOMS:
        await ws.send_json({"type": "error", "payload": {"msg": "Sala não encontrada"}})
        await ws.close()
        return
    ws._player_id = playerId  # attach for filtering
    WS_CONNS.setdefault(code, []).append(ws)
    try:
        await ws.send_json({"type": "state", "payload": public_room(ROOMS[code], playerId)})
        while True:
            data = await ws.receive_json()
            # Keep-alive / ping
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
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown():
    for t in SIM_TASKS.values():
        t.cancel()
