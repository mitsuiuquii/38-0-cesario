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

# ----------------------------- CORREÇÃO AQUI: Mount + CORS -----------------------------
# O CORS precisa ser adicionado ANTES do include_router para o Render aceitar o handshake do WS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://38-0-cesarioo.vercel.app",  # Teu front da Vercel
        "http://localhost:3000",             # Teste local
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")

# ----------------------------- O TEU ESTADO ORIGINAL -----------------------------
ROOMS: Dict[str, dict] = {}
WS_CONNS: Dict[str, List[WebSocket]] = {}
SIM_TASKS: Dict[str, asyncio.Task] = {}
NEXT_ROUND_EVENTS: Dict[str, asyncio.Event] = {}

SPEED_MS = {"slow": 1000, "fast": 220, "turbo": 55}
LEAGUE_SIZE = 20
COPA_BRASIL_SIZE = 16
CUP_SIZE = 8  # Libertadores / Sul-Americana

INTL_CLUBS = [
    ("River Plate", "ARG", "#E2231A"),
    ("Boca Juniors", "ARG", "#0E4DA4"),
    ("Peñarol", "URU", "#FFC107"),
    ("Nacional", "URU", "#FFFFFF"),
    ("Olímpia", "PAR", "#1B1B1B"),
    ("LDU Quito", "EQU", "#FFFFFF"),
    ("Colo-Colo", "CHI", "#FFFFFF"),
    ("Independiente", "ARG", "#E2231A"),
    ("Cerro Porteño", "PAR", "#E2231A"),
    ("Universidad Católica", "CHI", "#0E4DA4"),
    ("Estudiantes", "ARG", "#E2231A"),
    ("Vélez Sarsfield", "ARG", "#FFFFFF"),
]

def gen_room_code() -> str:
    while True:
        c = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if c not in ROOMS:
            return c

def new_player_id() -> str:
    return uuid.uuid4().hex[:12]

def empty_squad(formation: str) -> dict:
    return {slot["id"]: None for slot in FORMATIONS[formation]}

def get_next_round_event(code: str) -> asyncio.Event:
    if code not in NEXT_ROUND_EVENTS:
        NEXT_ROUND_EVENTS[code] = asyncio.Event()
    return NEXT_ROUND_EVENTS[code]

def public_room(room: dict, viewer_id: Optional[str] = None) -> dict:
    show_ovr = bool(room["showOvr"])
    teams_pub = []
    for t in room["teams"]:
        squad = {}
        for slot_id, p in t["squad"].items():
            if p is None:
                squad[slot_id] = None
            else:
                pub = {**p}
                hide = False
                if room["status"] in ("simulating", "finished"):
                    hide = True
                elif not show_ovr and viewer_id is not None and t["id"] != viewer_id:
                    hide = True
                if hide:
                    pub.pop("ovr", None)
                squad[slot_id] = pub
        ovr_val = round(team_ovr(t["squad"]), 1) if any(t["squad"].values()) else 0
        teams_pub.append({**t, "squad": squad,
                           "ovr": ovr_val if (room["status"] not in ("simulating", "finished")) else (
                               ovr_val if (t["id"] == viewer_id or room["showOvr"]) else None
                           )})
    sim = room.get("sim")
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
        "draftedPlayerNames": list(room.get("draftedPlayerNames", set())),
        "speed": room.get("speed", "fast"),
        "sim": sim_public(sim) if sim else None,
    }

def sim_public(sim: dict) -> dict:
    if not sim:
        return None
    comps_pub = {}
    for cid, comp in sim["competitions"].items():
        comps_pub[cid] = {
            "id": comp["id"], "name": comp["name"], "type": comp["type"],
            "status": comp["status"], "currentPhaseIdx": comp["currentPhaseIdx"],
            "phases": comp["phases"], "standings": comp.get("standings"),
            "groups": comp.get("groups"), "bracket": comp.get("bracket"),
            "winner_id": comp.get("winner_id"), "teamIds": comp.get("teamIds", []),
        }
    return {
        "active": sim["active"], "teams": sim["teams"], "competitions": comps_pub,
        "currentMinute": sim.get("currentMinute", 0), "currentMatches": sim.get("currentMatches", []),
    }

async def broadcast(code: str, kind: str = "state", payload: Optional[dict] = None):
    if code not in WS_CONNS:
        return
    if kind == "state":
        for ws in list(WS_CONNS.get(code, [])):
            try:
                viewer_id = getattr(ws, "_player_id", None)
                await ws.send_json({"type": "state", "payload": public_room(ROOMS[code], viewer_id)})
            except Exception:
                pass
    else:
        msg = {"type": kind, "payload": payload or {}}
        for ws in list(WS_CONNS.get(code, [])):
            try:
                await ws.send_json(msg)
            except Exception:
                pass

def assign_random_club_for_turn(room: dict) -> str:
    team = room["teams"][room["draftOrder"][room["currentTurnIdx"]]]
    open_slots = [s for s in FORMATIONS[team["formation"]] if team["squad"][s["id"]] is None]
    drafted_names = room["draftedPlayerNames"]
    used_labels = room.get("usedSquadLabels", set())
    
    labels = list(all_squad_labels())
    random.shuffle(labels)
    for label in labels:
        if label in used_labels:
            continue
        squad = get_squad_by_label(label)
        for p in squad["players"]:
            if p["name"] in drafted_names:
                continue
            for slot in open_slots:
                if slot_accepts_player(slot["pos"], p["pos"]):
                    return label
    return labels[0]

def players_for_assigned_club(room: dict) -> List[dict]:
    label = room["assignedClub"]
    squad = get_squad_by_label(label)
    if not squad: return []
    team = room["teams"][room["draftOrder"][room["currentTurnIdx"]]]
    open_slots = [s for s in FORMATIONS[team["formation"]] if team["squad"][s["id"]] is None]
    drafted_names = room["draftedPlayerNames"]
    out = []
    for p in squad["players"]:
        if p["name"] in drafted_names: continue
        valid_slots = [s["id"] for s in open_slots if slot_accepts_player(s["pos"], p["pos"])]
        if not valid_slots: continue
        out.append({
            "id": f"{squad['club']}-{squad['year']}-{p['name']}",
            "name": p["name"], "positions": p["pos"], "ovr": p["ovr"],
            "club": squad["club"], "year": squad["year"], "squad_label": squad["label"],
            "color": squad["color"], "accent": squad["accent"], "valid_slots": valid_slots,
        })
    return out

def advance_turn(room: dict):
    n = len(room["teams"])
    total_picks = n * 11
    if room["picksMade"] >= total_picks:
        room["status"] = "ready_to_sim"
        room["assignedClub"] = None
        room["availablePlayers"] = []
        return
    room["currentTurnIdx"] += 1
    if room["currentTurnIdx"] >= n:
        room["pickRound"] += 1
        room["draftOrder"].reverse()
        room["currentTurnIdx"] = 0
    room["assignedClub"] = assign_random_club_for_turn(room)
    room["availablePlayers"] = players_for_assigned_club(room)

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
    cardId: str
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
             "color": s["color"], "accent": s["accent"], "player_count": len(s["players"])} for s in SQUADS]

@api.post("/rooms")
async def create_room(req: CreateRoomReq):
    code = gen_room_code()
    host_id = new_player_id()
    room = {
        "code": code, "password": req.password or "", "hostId": host_id, "showOvr": req.showOvr, "status": "lobby",
        "teams": [{"id": host_id, "name": req.name, "teamName": req.teamName or req.name, "formation": "4-3-3", "squad": empty_squad("4-3-3")}],
        "draftOrder": [], "currentTurnIdx": 0, "pickRound": 0, "picksMade": 0, "draftedPlayerNames": set(), "usedSquadLabels": set(),
        "assignedClub": None, "availablePlayers": [], "speed": "fast", "sim": None, "createdAt": time.time(),
    }
    ROOMS[code] = room
    return {"code": code, "playerId": host_id}

@api.post("/rooms/{code}/join")
async def join_room(code: str, req: JoinRoomReq):
    room = ROOMS.get(code.upper())
    if not room: raise HTTPException(404, "Sala não encontrada")
    if room["status"] != "lobby": raise HTTPException(400, "Draft já iniciado nesta sala")
    if room["password"] and req.password != room["password"]: raise HTTPException(403, "Senha incorreta")
    if len(room["teams"]) >= 12: raise HTTPException(400, "Sala cheia (máx 12)")
    pid = new_player_id()
    room["teams"].append({"id": pid, "name": req.name, "teamName": req.teamName or req.name, "formation": "4-3-3", "squad": empty_squad("4-3-3")})
    await broadcast(code, "state")
    return {"code": code, "playerId": pid}

@api.get("/rooms/{code}")
async def get_room(code: str, playerId: Optional[str] = None):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    return public_room(room, playerId)

@api.post("/rooms/{code}/update-team")
async def update_team(code: str, req: UpdateTeamReq):
    room = ROOMS.get(code.upper())
    if not room: raise HTTPException(404, "Sala não encontrada")
    team = next((t for t in room["teams"] if t["id"] == req.playerId), None)
    if not team: raise HTTPException(404, "Jogador não está nesta sala")
    if room["status"] != "lobby": raise HTTPException(400, "Não é possível alterar após o draft iniciar")
    if req.teamName is not None: team["teamName"] = req.teamName[:60]
    if req.formation is not None and req.formation in FORMATIONS:
        team["formation"] = req.formation
        team["squad"] = empty_squad(req.formation)
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/host-update")
async def host_update(code: str, req: HostUpdateReq):
    room = ROOMS.get(code.upper())
    if not room: raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]: raise HTTPException(403, "Somente o anfitrião pode alterar")
    if req.showOvr is not None: room["showOvr"] = req.showOvr
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/start-draft")
async def start_draft(code: str, req: HostUpdateReq):
    room = ROOMS.get(code.upper())
    if not room: raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]: raise HTTPException(403, "Somente o anfitrião pode iniciar")
    if room["status"] != "lobby": raise HTTPException(400, "Draft já iniciado")
    if len(room["teams"]) < 2: raise HTTPException(400, "Mínimo 2 jogadores para iniciar")
    for t in room["teams"]: t["squad"] = empty_squad(t["formation"])
    order_idx = list(range(len(room["teams"])))
    random.shuffle(order_idx)
    room["draftOrder"] = order_idx
    room["status"] = "drafting"
    room["currentTurnIdx"] = 0
    room["pickRound"] = 0
    room["picksMade"] = 0
    room["draftedPlayerNames"] = set()
    room["usedSquadLabels"] = set()
    room["sim"] = None
    room["assignedClub"] = assign_random_club_for_turn(room)
    room["availablePlayers"] = players_for_assigned_club(room)
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/draft-pick")
async def draft_pick(code: str, req: DraftPickReq):
    room = ROOMS.get(code.upper())
    if not room: raise HTTPException(404, "Sala não encontrada")
    if room["status"] != "drafting": raise HTTPException(400, "Draft não está em andamento")
    current_team_idx = room["draftOrder"][room["currentTurnIdx"]]
    team = room["teams"][current_team_idx]
    if team["id"] != req.playerId: raise HTTPException(403, "Não é a sua vez")
    card = next((p for p in room["availablePlayers"] if p["id"] == req.cardId), None)
    if not card: raise HTTPException(400, "Jogador não disponível neste clube")
    if card["name"] in room["draftedPlayerNames"]: raise HTTPException(400, "Esse jogador já foi escolhido")
    if req.slotId not in card["valid_slots"]: raise HTTPException(400, "Posição inválida")
    if team["squad"][req.slotId] is not None: raise HTTPException(400, "Posição já preenchida")
    
    squad_label = card.get("squad_label")
    if squad_label and squad_label not in room.get("usedSquadLabels", set()):
        if "usedSquadLabels" not in room: room["usedSquadLabels"] = set()
        room["usedSquadLabels"].add(squad_label)
    
    team["squad"][req.slotId] = {
        "id": card["id"], "name": card["name"], "ovr": card["ovr"],
        "positions": card["positions"], "squad_label": card["squad_label"],
        "color": card["color"], "accent": card["accent"],
    }
    room["draftedPlayerNames"].add(card["name"])
    room["picksMade"] += 1
    await broadcast(code, "pick", {"team_id": team["id"], "slotId": req.slotId, "card": team["squad"][req.slotId]})
    advance_turn(room)
    await broadcast(code, "state")
    return {"ok": True}

@api.post("/rooms/{code}/set-speed")
async def set_speed(code: str, req: SpeedReq):
    room = ROOMS.get(code.upper())
    if not room: raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]: raise HTTPException(403, "Somente o anfitrião pode mudar")
    if req.speed not in SPEED_MS: raise HTTPException(400, "Velocidade inválida")
    room["speed"] = req.speed
    await broadcast(code, "state")
    return {"ok": True}

# ----------------------------- O TEU MOTOR DE JOGO COMPLETO -----------------------------
def make_team_from_squad_label(label: str, formation: str, used_names: set) -> Optional[dict]:
    squad = get_squad_by_label(label)
    if not squad: return None
    slots = FORMATIONS[formation]
    candidates = sorted([p for p in squad["players"] if p["name"] not in used_names], key=lambda x: -x["ovr"])
    placement = {}
    placed_names = set()
    PRIORITY = {"GK": 0, "ST": 1, "CB": 2, "LB": 3, "RB": 3, "LW": 4, "RW": 4, "CAM": 5, "LM": 6, "RM": 6, "CDM": 7, "CM": 8}
    ordered_slots = sorted(slots, key=lambda s: PRIORITY.get(s["pos"], 9))
    for slot in ordered_slots:
        pick = None
        for p in candidates:
            if p["name"] in placed_names: continue
            if slot_accepts_player(slot["pos"], p["pos"]):
                pick = p
                break
        if not pick: return None
        placement[slot["id"]] = pick
        placed_names.add(pick["name"])

    team_squad = {sid: {
        "id": f"{squad['club']}-{squad['year']}-{p['name']}", "name": p["name"], "ovr": p["ovr"], "positions": p["pos"],
        "squad_label": squad["label"], "color": squad["color"], "accent": squad["accent"],
    } for sid, p in placement.items()}

    return {"label": squad["label"], "color": squad["color"], "accent": squad["accent"], "formation": formation, "squad": team_squad, "names": placed_names}

def build_league_teams(room: dict) -> List[dict]:
    league_teams = []
    used_labels = set()
    blocked_names_for_npc = set(room["draftedPlayerNames"])

    for t in room["teams"]:
        league_teams.append({
            "id": t["id"], 
            "teamName": t["teamName"], 
            "isNpc": False,
            "country": "BRA", 
            "color": "#39FF14", 
            "accent": "#FFD700",
            "ovr": round(team_ovr(t["squad"]), 1), 
            "squad": t["squad"],
            "formation": t["formation"], 
            "label": None,
        })

    candidate_labels = [s["label"] for s in SQUADS if s["label"] not in used_labels]
    random.shuffle(candidate_labels)
    npc_idx = 0

    while len(league_teams) < LEAGUE_SIZE and candidate_labels:
        chosen = None
        for label in list(candidate_labels):
            built = make_team_from_squad_label(label, random.choice(list(FORMATIONS.keys())), blocked_names_for_npc)
            if built is not None:
                chosen = built
                candidate_labels.remove(label)
                used_labels.add(label)
                break

        if not chosen:
            for label in list(candidate_labels):
                built = make_team_from_squad_label(label, "4-3-3", set())
                if built is not None:
                    chosen = built
                    candidate_labels.remove(label)
                    used_labels.add(label)
                    break

        if not chosen:
            break

        sq = get_squad_by_label(chosen["label"])
        league_teams.append({
            "id": f"npc_{npc_idx}", 
            "teamName": chosen["label"],
            "isNpc": True, 
            "country": "BRA", 
            "color": sq["color"], 
            "accent": sq["accent"],
            "ovr": round(team_ovr(chosen["squad"]), 1), 
            "squad": chosen["squad"], 
            "formation": chosen["formation"], 
            "label": chosen["label"],
        })
        npc_idx += 1

    npc_backup_count = 1
    while len(league_teams) < LEAGUE_SIZE:
        formacao_aleatoria = random.choice(list(FORMATIONS.keys()))
        squad_vazio = empty_squad(formacao_aleatoria)
        league_teams.append({
            "id": f"npc_generic_{npc_idx}_{uuid.uuid4().hex[:4]}",
            "teamName": f"Bot FC {npc_backup_count}", 
            "isNpc": True, 
            "country": "BRA", 
            "color": "#4A5568", 
            "accent": "#CBD5E0", 
            "ovr": 75.0, 
            "squad": squad_vazio, 
            "formation": formacao_aleatoria, 
            "label": None,
        })
        npc_idx += 1
        npc_backup_count += 1

    if len(league_teams) % 2 == 1:
        league_teams = league_teams[:-1]

    random.shuffle(league_teams)
    return league_teams


def build_intl_teams(used_labels: set, used_names: set, count: int) -> List[dict]:
    out = []
    intl_pool = list(INTL_CLUBS)
    random.shuffle(intl_pool)
    label_pool = [s["label"] for s in SQUADS if s["label"] not in used_labels]
    random.shuffle(label_pool)
    
    for i in range(count):
        club_name, country, color = intl_pool[i % len(intl_pool)]
        
        built = {
            "squad": empty_squad("4-3-3"),
            "formation": "4-3-3",
            "label": None,
            "ovr": 74.0
        }
        
        has_chosen = False
        for label in list(label_pool):
            cand = make_team_from_squad_label(label, random.choice(list(FORMATIONS.keys())), used_names)
            if cand is not None:
                built = cand
                label_pool.remove(label)
                used_labels.add(label)
                has_chosen = True
                break
                
        if not has_chosen:
            for label in list(label_pool):
                cand = make_team_from_squad_label(label, "4-3-3", set())
                if cand is not None:
                    built = cand
                    label_pool.remove(label)
                    used_labels.add(label)
                    break
        
        if built.get("label") is not None:
            team_ovr_val = round(team_ovr(built["squad"]), 1)
        else:
            team_ovr_val = built["ovr"]
        
        out.append({
            "id": f"intl_{country.lower()}_{i}_{random.randint(1000,9999)}", 
            "teamName": club_name, 
            "isNpc": True, 
            "country": country,
            "color": color, 
            "accent": "#FFFFFF", 
            "ovr": team_ovr_val, 
            "squad": built["squad"], 
            "formation": built["formation"], 
            "label": built["label"],
        })
        
    return out

def pick_scorer(team_obj):
    pool = []
    for p in team_obj["squad"].values():
        if p is None: continue
        pos = p.get("positions", [])
        weight = 1
        if "ST" in pos: weight = 8
        elif any(x in pos for x in ["LW", "RW", "CAM"]): weight = 5
        elif any(x in pos for x in ["CM", "LM", "RM"]): weight = 3
        elif any(x in pos for x in ["CB", "LB", "RB", "CDM"]): weight = 1
        if "GK" in pos: weight = 0
        pool.extend([p] * weight)
    return random.choice(pool) if pool else None

def make_match(sim_teams: dict, home_id: str, away_id: str, tie_id: Optional[str] = None, leg: Optional[int] = None, neutral: bool = False) -> dict:
    ht = sim_teams[home_id]
    at = sim_teams[away_id]
    home_form = random.uniform(-5, 5)
    away_form = random.uniform(-5, 5)
    hg, ag, events = simulate_match_goals(ht["ovr"], at["ovr"], home_form, away_form)
    final_events = []
    for ev in events:
        if "flavor" not in ev:
            scorer = pick_scorer(ht if ev["team"] == "home" else at)
            ev["player_name"] = scorer["name"] if scorer else "Gol"
        final_events.append(ev)
    return {
        "home_id": home_id, "away_id": away_id, "home_score": 0, "away_score": 0,
        "home_name": ht["teamName"], "away_name": at["teamName"], "home_color": ht["color"], "away_color": at["color"],
        "events": final_events, "emitted": [], "tie_id": tie_id, "leg": leg, "neutral": neutral,
    }

def make_league_comp(league_teams: List[dict]) -> dict:
    fixtures = generate_fixtures([t["id"] for t in league_teams])
    phases = []
    sim_teams = {t["id"]: t for t in league_teams}
    for r_idx, rd in enumerate(fixtures):
        matches = [make_match(sim_teams, h, a) for (h, a) in rd]
        phases.append({"name": f"Rodada {r_idx + 1}", "matches": matches})
    standings = {t["id"]: {"id": t["id"], "teamName": t["teamName"], "isNpc": t["isNpc"], "ovr": t["ovr"], "P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "GD": 0, "Pts": 0} for t in league_teams}
    return {"id": "league", "name": "Brasileirão Série A", "type": "league", "teamIds": [t["id"] for t in league_teams], "status": "ready", "currentPhaseIdx": -1, "phases": phases, "standings": standings, "winner_id": None}

def make_copa_brasil_comp(sim_teams: dict, league_team_ids: List[str]) -> dict:
    qualifying = random.sample(league_team_ids, COPA_BRASIL_SIZE)
    random.shuffle(qualifying)
    r16_matches = []
    for i in range(0, COPA_BRASIL_SIZE, 2):
        h, a = qualifying[i], qualifying[i + 1]
        r16_matches.append(make_match(sim_teams, h, a))
    phases = [{"name": "Oitavas de Final", "matches": r16_matches}]
    bracket = {"stages": [{"name": "Oitavas", "matchups": [(m["home_id"], m["away_id"], None) for m in r16_matches]}]}
    return {"id": "copa_brasil", "name": "Copa do Brasil", "type": "knockout", "teamIds": qualifying, "status": "ready", "currentPhaseIdx": -1, "phases": phases, "bracket": bracket, "winner_id": None, "ties": {}}

def make_cup_comp(sim_teams: dict, b_team_ids: List[str], intl_team_ids: List[str], cup_id: str, cup_name: str) -> dict:
    all_ids = b_team_ids + intl_team_ids
    random.shuffle(all_ids)
    group_a = all_ids[:4]
    group_b = all_ids[4:8]
    a_rounds = generate_fixtures(group_a)
    b_rounds = generate_fixtures(group_b)
    phases = []
    for ri in range(len(a_rounds)):
        matches_a = [make_match(sim_teams, h, a) for (h, a) in a_rounds[ri]]
        matches_b = [make_match(sim_teams, h, a) for (h, a) in b_rounds[ri]]
        phases.append({"name": f"Fase de Grupos – Rodada {ri + 1}", "matches": matches_a + matches_b})
    standings = {tid: {"id": tid, "teamName": sim_teams[tid]["teamName"], "isNpc": sim_teams[tid]["isNpc"], "ovr": sim_teams[tid]["ovr"], "country": sim_teams[tid]["country"], "P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "GD": 0, "Pts": 0, "group": "A" if tid in group_a else "B"} for tid in all_ids}
    return {"id": cup_id, "name": cup_name, "type": "groups_knockout", "teamIds": all_ids, "status": "ready", "currentPhaseIdx": -1, "phases": phases, "standings": standings, "groups": {"A": group_a, "B": group_b}, "winner_id": None, "ties": {}}

def tie_winner(tie: dict) -> str:
    a, b = tie["team_a_id"], tie["team_b_id"]
    agg_a, agg_b = tie["agg_a"], tie["agg_b"]
    if agg_a > agg_b: return a
    if agg_b > agg_a: return b
    away_a = tie.get("a_away_goals", 0)
    away_b = tie.get("b_away_goals", 0)
    if away_a > away_b: return a
    if away_b > away_a: return b
    return random.choice([a, b])

def update_tie_after_leg(tie: dict, m: dict):
    a = tie["team_a_id"]
    if m["home_id"] == a:
        tie["agg_a"] += m["home_score"]
        tie["agg_b"] += m["away_score"]
        tie["b_away_goals"] = tie.get("b_away_goals", 0) + m["away_score"]
    else:
        tie["agg_b"] += m["home_score"]
        tie["agg_a"] += m["away_score"]
        tie["a_away_goals"] = tie.get("a_away_goals", 0) + m["away_score"]

def generate_next_knockout_phase_copa(room: dict):
    sim = room["sim"]
    comp = sim["competitions"]["copa_brasil"]
    sim_teams = sim["teams"]
    cur_phase = comp["phases"][comp["currentPhaseIdx"]]
    
    if cur_phase["name"] == "Oitavas de Final":
        winners = [m["home_id"] if m["home_score"] > m["away_score"] else m["away_id"] for m in cur_phase["matches"]]
        qf_l1 = []
        for i in range(0, len(winners), 2):
            a, b = winners[i], winners[i + 1]
            tie_id = f"qf_{i // 2}"
            comp["ties"][tie_id] = {"tie_id": tie_id, "team_a_id": a, "team_b_id": b, "agg_a": 0, "agg_b": 0, "a_away_goals": 0, "b_away_goals": 0, "winner_id": None}
            qf_l1.append(make_match(sim_teams, a, b, tie_id=tie_id, leg=1))
        comp["phases"].append({"name": "Quartas — Ida", "matches": qf_l1})
        comp["bracket"]["stages"].append({"name": "Quartas Ida", "matchups": [(m["home_id"], m["away_id"], m["tie_id"]) for m in qf_l1]})
        return
    if cur_phase["name"] == "Quartas — Ida":
        qf_l2 = []
        for m in cur_phase["matches"]:
            tie_id = m["tie_id"]
            tie = comp["ties"][tie_id]
            qf_l2.append(make_match(sim_teams, tie["team_b_id"], tie["team_a_id"], tie_id=tie_id, leg=2))
        comp["phases"].append({"name": "Quartas — Volta", "matches": qf_l2})
        comp["bracket"]["stages"].append({"name": "Quartas Volta", "matchups": [(m["home_id"], m["away_id"], m["tie_id"]) for m in qf_l2]} )
        return
    if cur_phase["name"] == "Quartas — Volta":
        winners = []
        for tid, tie in comp["ties"].items():
            if tid.startswith("qf_"):
                tie["winner_id"] = tie_winner(tie)
                winners.append(tie["winner_id"])
        sf_l1 = []
        for i in range(0, len(winners), 2):
            a, b = winners[i], winners[i + 1]
            tie_id = f"sf_{i // 2}"
            comp["ties"][tie_id] = {"tie_id": tie_id, "team_a_id": a, "team_b_id": b, "agg_a": 0, "agg_b": 0, "a_away_goals": 0, "b_away_goals": 0, "winner_id": None}
            sf_l1.append(make_match(sim_teams, a, b, tie_id=tie_id, leg=1))
        comp["phases"].append({"name": "Semifinal — Ida", "matches": sf_l1})
        comp["bracket"]["stages"].append({"name": "Semifinal Ida", "matchups": [(m["home_id"], m["away_id"], m["tie_id"]) for m in sf_l1]})
        return
    if cur_phase["name"] == "Semifinal — Ida":
        sf_l2 = []
        for m in cur_phase["matches"]:
            tie_id = m["tie_id"]
            tie = comp["ties"][tie_id]
            sf_l2.append(make_match(sim_teams, tie["team_b_id"], tie["team_a_id"], tie_id=tie_id, leg=2))
        comp["phases"].append({"name": "Semifinal — Volta", "matches": sf_l2})
        comp["bracket"]["stages"].append({"name": "Semifinal Volta", "matchups": [(m["home_id"], m["away_id"], m["tie_id"]) for m in sf_l2]})
        return
    if cur_phase["name"] == "Semifinal — Volta":
        winners = []
        for tid, tie in comp["ties"].items():
            w = tie_winner(tie)
            tie["winner_id"] = w
            winners.append(w)
        f_l1 = []
        a, b = winners[0], winners[1]
        tie_id = "final_0"
        comp["ties"][tie_id] = {"tie_id": tie_id, "team_a_id": a, "team_b_id": b, "agg_a": 0, "agg_b": 0, "a_away_goals": 0, "b_away_goals": 0, "winner_id": None}
        f_l1.append(make_match(sim_teams, a, b, tie_id=tie_id, leg=1))
        comp["phases"].append({"name": "Final — Ida", "matches": f_l1})
        comp["bracket"]["stages"].append({"name": "Final Ida", "matchups": [(m["home_id"], m["away_id"], m["tie_id"]) for m in f_l1]})
        return
    if cur_phase["name"] == "Final — Ida":
        m = cur_phase["matches"][0]
        tie = comp["ties"]["final_0"]
        f_l2 = [make_match(sim_teams, tie["team_b_id"], tie["team_a_id"], tie_id="final_0", leg=2)]
        comp["phases"].append({"name": "Final — Volta", "matches": f_l2})
        return
    if cur_phase["name"] == "Final — Volta":
        tie = comp["ties"]["final_0"]
        comp["winner_id"] = tie_winner(tie)
        comp["status"] = "completed"

def generate_next_knockout_phase_cup(room: dict, cup_id: str):
    sim = room["sim"]
    comp = sim["competitions"][cup_id]
    sim_teams = sim["teams"]
    cur_phase = comp["phases"][comp["currentPhaseIdx"]]
    cur_name = cur_phase["name"]
    
    if cur_name == "Fase de Grupos – Rodada 6":
        standings = list(comp["standings"].values())
        group_a = sorted([s for s in standings if s["group"] == "A"], key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))
        group_b = sorted([s for s in standings if s["group"] == "B"], key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))
        a1, a2 = group_a[0]["id"], group_a[1]["id"]
        b1, b2 = group_b[0]["id"], group_b[1]["id"]
        
        sf_l1 = []
        t1 = f"libsf_0"
        comp["ties"][t1] = {"tie_id": t1, "team_a_id": a1, "team_b_id": b2, "agg_a": 0, "agg_b": 0, "winner_id": None}
        sf_l1.append(make_match(sim_teams, a1, b2, tie_id=t1, leg=1))
        
        t2 = f"libsf_1"
        comp["ties"][t2] = {"tie_id": t2, "team_a_id": b1, "team_b_id": a2, "agg_a": 0, "agg_b": 0, "winner_id": None}
        sf_l1.append(make_match(sim_teams, b1, a2, tie_id=t2, leg=1))
        comp["phases"].append({"name": "Semifinal — Ida", "matches": sf_l1})
        return
    if cur_name == "Semifinal — Ida":
        sf_l2 = []
        for m in cur_phase["matches"]:
            tid = m["tie_id"]
            tie = comp["ties"][tid]
            sf_l2.append(make_match(sim_teams, tie["team_b_id"], tie["team_a_id"], tie_id=tid, leg=2))
        comp["phases"].append({"name": "Semifinal — Volta", "matches": sf_l2})
        return
    if cur_name == "Semifinal — Volta":
        winners = []
        for tid, tie in comp["ties"].items():
            if tid.startswith("libsf_"):
                tie["winner_id"] = tie_winner(tie)
                winners.append(tie["winner_id"])
        final = [make_match(sim_teams, winners[0], winners[1], neutral=True)]
        comp["phases"].append({"name": "Final (Jogo Único)", "matches": final})
        return
    if cur_name == "Final (Jogo Único)":
        m = cur_phase["matches"][0]
        if m["home_score"] > m["away_score"]: comp["winner_id"] = m["home_id"]
        elif m["away_score"] > m["home_score"]: comp["winner_id"] = m["away_id"]
        else: comp["winner_id"] = random.choice([m["home_id"], m["away_id"]])
        comp["status"] = "completed"

async def simulate_phase(code: str, comp_id: str):
    room = ROOMS[code]
    sim = room["sim"]
    comp = sim["competitions"][comp_id]
    phase = comp["phases"][comp["currentPhaseIdx"]]
    matches = phase["matches"]
    sim["currentMatches"] = matches
    sim["currentMinute"] = 0
    comp["status"] = "playing"
    await broadcast(code, "state")
    await broadcast(code, "round_start", {"comp_id": comp_id, "phaseIdx": comp["currentPhaseIdx"], "phaseName": phase["name"], "matches": matches})
    
    for minute in range(1, 91):
        speed = room.get("speed", "fast")
        delay = SPEED_MS.get(speed, 220) / 1000.0
        await asyncio.sleep(delay)
        sim["currentMinute"] = minute
        tick_events = []
        for m_idx, m in enumerate(matches):
            fired = [e for e in m["events"] if e["minute"] == minute]
            for ev in fired:
                if "flavor" not in ev:
                    if ev["team"] == "home": m["home_score"] += 1
                    else: m["away_score"] += 1
                m["emitted"].append(ev)
                tick_events.append({"matchIdx": m_idx, "event": ev, "home_score": m["home_score"], "away_score": m["away_score"]})
        if tick_events:
            await broadcast(code, "tick", {"minute": minute, "events": tick_events})
            
    if comp["type"] == "league":
        for m in matches:
            h, a = m["home_id"], m["away_id"]
            hs, as_ = m["home_score"], m["away_score"]
            st = comp["standings"]
            st[h]["P"] += 1; st[a]["P"] += 1
            st[h]["GF"] += hs; st[h]["GA"] += as_; st[h]["GD"] = st[h]["GF"] - st[h]["GA"]
            st[a]["GF"] += as_; st[a]["GA"] += hs; st[a]["GD"] = st[a]["GF"] - st[a]["GA"]
            if hs > as_: st[h]["W"] += 1; st[h]["Pts"] += 3; st[a]["L"] += 1
            elif as_ > hs: st[a]["W"] += 1; st[a]["Pts"] += 3; st[h]["L"] += 1
            else: st[h]["D"] += 1; st[h]["Pts"] += 1; st[a]["D"] += 1; st[a]["Pts"] += 1
        if comp["currentPhaseIdx"] >= len(comp["phases"]) - 1:
            standings_sorted = sorted(comp["standings"].values(), key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))
            comp["winner_id"] = standings_sorted[0]["id"]
            comp["status"] = "completed"
            
    elif comp["type"] == "knockout":
        for m in matches:
            if m.get("tie_id"):
                tie = comp["ties"][m["tie_id"]]
                update_tie_after_leg(tie, m)
        if comp["currentPhaseIdx"] >= len(comp["phases"]) - 1:
            generate_next_knockout_phase_copa(room)
            
    elif comp["type"] == "groups_knockout":
        if "Fase de Grupos" in phase["name"]:
            for m in matches:
                h, a = m["home_id"], m["away_id"]
                hs, as_ = m["home_score"], m["away_score"]
                st = comp["standings"]
                st[h]["P"] += 1; st[a]["P"] += 1
                st[h]["GF"] += hs; st[h]["GA"] += as_; st[h]["GD"] = st[h]["GF"] - st[h]["GA"]
                st[a]["GF"] += as_; st[a]["GA"] += hs; st[a]["GD"] = st[a]["GF"] - st[a]["GA"]
                if hs > as_: st[h]["W"] += 1; st[h]["Pts"] += 3; st[a]["L"] += 1
                elif as_ > hs: st[a]["W"] += 1; st[a]["Pts"] += 3; st[h]["L"] += 1
                else: st[h]["D"] += 1; st[h]["Pts"] += 1; st[a]["D"] += 1; st[a]["Pts"] += 1
        else:
            for m in matches:
                if m.get("tie_id"):
                    tie = comp["ties"][m["tie_id"]]
                    update_tie_after_leg(tie, m)
        generate_next_knockout_phase_cup(room, comp_id)
        
    if comp["status"] != "completed": comp["status"] = "round_break"
    await broadcast(code, "round_end", {"comp_id": comp_id, "phaseIdx": comp["currentPhaseIdx"], "standings": list((comp.get("standings") or {}).values()), "winner_id": comp.get("winner_id")})
    if comp["status"] == "completed": advance_to_next_competition(room)
    await broadcast(code, "state")

def advance_to_next_competition(room: dict):
    sim = room["sim"]
    order = ["league", "copa_brasil", "libertadores", "sulamericana"]
    cur = sim["active"]
    cur_idx = order.index(cur) if cur in order else len(order)
    if cur == "league":
        league = sim["competitions"]["league"]
        standings = sorted(league["standings"].values(), key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))
        top4 = [s["id"] for s in standings[:4]]
        five_eight = [s["id"] for s in standings[4:8]]
        used_labels = set()
        used_names = set()
        for t in sim["teams"].values():
            if t.get("label"): used_labels.add(t["label"])
            for p in t["squad"].values():
                if p: used_names.add(p["name"])
        intl_lib = build_intl_teams(used_labels, used_names, 4)
        intl_sul = build_intl_teams(used_labels, used_names, 4)
        for t in intl_lib + intl_sul: sim["teams"][t["id"]] = t
        lib = make_cup_comp(sim["teams"], top4, [t["id"] for t in intl_lib], "libertadores", "Copa Libertadores")
        sul = make_cup_comp(sim["teams"], five_eight, [t["id"] for t in intl_sul], "sulamericana", "Copa Sul-Americana")
        copa = make_copa_brasil_comp(sim["teams"], list(league["standings"].keys()))
        sim["competitions"]["copa_brasil"] = copa
        sim["competitions"]["libertadores"] = lib
        sim["competitions"]["sulamericana"] = sul
    next_id = None
    for cid in order[cur_idx + 1:]:
        if cid in sim["competitions"] and sim["competitions"][cid]["status"] != "completed":
            next_id = cid
            break
    if next_id:
        sim["active"] = next_id
        sim["competitions"][next_id]["status"] = "ready"
    else: sim["active"] = "completed"

async def delayed_sim(code: str, comp_id: str):
    await asyncio.sleep(0.5)  # deixa o broadcast chegar antes
    comp = ROOMS[code]["sim"]["competitions"][comp_id]
    comp["currentPhaseIdx"] = 0
    await simulate_phase(code, comp_id)

@api.post("/rooms/{code}/start-sim")
async def init_season(code: str, req: HostUpdateReq):
    code = code.upper()
    room = ROOMS.get(code)
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]:
        raise HTTPException(403, "Somente anfitrião")
    if room["status"] != "ready_to_sim":
        raise HTTPException(400, "Draft incompleto")
    if code in SIM_TASKS and not SIM_TASKS[code].done():
        raise HTTPException(400, "Outra simulação em curso")

    league_teams = build_league_teams(room)
    sim_teams = {t["id"]: t for t in league_teams}
    league_comp = make_league_comp(league_teams)

    room["sim"] = {
        "active": "league",
        "teams": sim_teams,
        "competitions": {"league": league_comp},
        "currentMinute": 0,
        "currentMatches": [],
    }
    room["status"] = "simulating"

    await broadcast(code, "state")

    SIM_TASKS[code] = asyncio.create_task(delayed_sim(code, "league"))
    return {"ok": True}

@api.post("/rooms/{code}/next-round")
async def advance_round(code: str, req: HostUpdateReq):
    code = code.upper()
    room = ROOMS.get(code)
    if not room or not room.get("sim"): raise HTTPException(404, "Sala ou temporada não iniciada")
    if req.playerId != room["hostId"]: raise HTTPException(403, "Somente anfitrião")
    sim = room["sim"]
    active = sim["active"]
    if active == "completed": raise HTTPException(400, "Temporada finalizada")
    comp = sim["competitions"].get(active)
    if not comp: raise HTTPException(400, "Competição inexistente")
    if comp["status"] == "playing": raise HTTPException(400, "Rodada em andamento")
    if comp["status"] not in ("ready", "round_break"): raise HTTPException(400, f"Estado inválido: {comp['status']}")
    
    comp["currentPhaseIdx"] += 1
    if comp["currentPhaseIdx"] >= len(comp["phases"]): raise HTTPException(400, "Sem fases pendentes")
    if code in SIM_TASKS and not SIM_TASKS[code].done(): raise HTTPException(400, "Outra simulação em curso")
    
    SIM_TASKS[code] = asyncio.create_task(simulate_phase(code, active))
    return {"ok": True}

@api.post("/rooms/{code}/switch-competition")
async def switch_competition(code: str, req: HostUpdateReq):
    return {"ok": True}

app.include_router(api)

# ----------------------------- CORREÇÃO AQUI: WebSocket DIRETO NO APP -----------------------------
# Rodar direto no 'app' com extração manual de Query evita o erro 404 e rejeição de proxies no Render
@app.websocket("/api/ws/{code}")
async def ws_endpoint(ws: WebSocket, code: str):
    code = code.upper()
    await ws.accept()
    
    player_id = ws.query_params.get("playerId")
    ws._player_id = player_id
    
    if code not in ROOMS:
        try:
            await ws.send_json({"type": "error", "payload": {"msg": "Sala não encontrada"}})
            await ws.close()
        except Exception:
            pass
        return
        
    WS_CONNS.setdefault(code, []).append(ws)
    
    try:
        await ws.send_json({"type": "state", "payload": public_room(ROOMS[code], player_id)})
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
            if code in WS_CONNS and ws in WS_CONNS[code]:
                WS_CONNS[code].remove(ws)
        except Exception:
            pass