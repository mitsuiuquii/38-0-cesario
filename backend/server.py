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
ROOMS: Dict[str, dict] = {}
WS_CONNS: Dict[str, List[WebSocket]] = {}
SIM_TASKS: Dict[str, asyncio.Task] = {}
NEXT_ROUND_EVENTS: Dict[str, asyncio.Event] = {}

SPEED_MS = {"slow": 1000, "fast": 220, "turbo": 55}
LEAGUE_SIZE = 20
COPA_BRASIL_SIZE = 16
CUP_SIZE = 8  # Libertadores / Sul-Americana

# Fake "international" club names for continental NPC fillers
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


# ----------------------------- Generic helpers -----------------------------
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


# ----------------------------- State serialisation -----------------------------
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
                # Hide OVR from opponents during draft if showOvr is off.
                # During simulation / final, ALWAYS hide OVR from squad cards
                # (per user request: ver elencos sem revelar OVR).
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
                           # also hide team OVR during simulation/finished from opponents
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
    """Strip transient internal fields from sim state."""
    if not sim:
        return None
    comps_pub = {}
    for cid, comp in sim["competitions"].items():
        comps_pub[cid] = {
            "id": comp["id"],
            "name": comp["name"],
            "type": comp["type"],
            "status": comp["status"],
            "currentPhaseIdx": comp["currentPhaseIdx"],
            "phases": comp["phases"],
            "standings": comp.get("standings"),
            "groups": comp.get("groups"),
            "bracket": comp.get("bracket"),
            "winner_id": comp.get("winner_id"),
            "teamIds": comp.get("teamIds", []),
        }
    return {
        "active": sim["active"],
        "teams": sim["teams"],  # public catalog id -> {teamName, isNpc, country, color, etc}
        "competitions": comps_pub,
        "currentMinute": sim.get("currentMinute", 0),
        "currentMatches": sim.get("currentMatches", []),
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


# ----------------------------- Draft helpers -----------------------------
def assign_random_club_for_turn(room: dict) -> str:
    """Random squad label that has at least one valid player for the picker's open slots."""
    team = room["teams"][room["draftOrder"][room["currentTurnIdx"]]]
    open_slots = [s for s in FORMATIONS[team["formation"]] if team["squad"][s["id"]] is None]
    drafted_names = room["draftedPlayerNames"]
    labels = list(all_squad_labels())
    random.shuffle(labels)
    for label in labels:
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
    if not squad:
        return []
    team = room["teams"][room["draftOrder"][room["currentTurnIdx"]]]
    open_slots = [s for s in FORMATIONS[team["formation"]] if team["squad"][s["id"]] is None]
    drafted_names = room["draftedPlayerNames"]
    out = []
    for p in squad["players"]:
        if p["name"] in drafted_names:
            continue
        valid_slots = [s["id"] for s in open_slots if slot_accepts_player(s["pos"], p["pos"])]
        if not valid_slots:
            continue
        out.append({
            "id": f"{squad['club']}-{squad['year']}-{p['name']}",
            "name": p["name"], "positions": p["pos"], "ovr": p["ovr"],
            "club": squad["club"], "year": squad["year"], "squad_label": squad["label"],
            "color": squad["color"], "accent": squad["accent"],
            "valid_slots": valid_slots,
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


# ----------------------------- HTTP request models -----------------------------
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


# ----------------------------- REST: rooms -----------------------------
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
        "draftedPlayerNames": set(),
        "assignedClub": None,
        "availablePlayers": [],
        "speed": "fast",
        "sim": None,
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
    # Reset squads in case of replay-with-same-teams
    for t in room["teams"]:
        t["squad"] = empty_squad(t["formation"])
    order_idx = list(range(len(room["teams"])))
    random.shuffle(order_idx)
    room["draftOrder"] = order_idx
    room["status"] = "drafting"
    room["currentTurnIdx"] = 0
    room["pickRound"] = 0
    room["picksMade"] = 0
    room["draftedPlayerNames"] = set()
    room["sim"] = None
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
    card = next((p for p in room["availablePlayers"] if p["id"] == req.cardId), None)
    if not card:
        raise HTTPException(400, "Jogador não disponível neste clube")
    if card["name"] in room["draftedPlayerNames"]:
        raise HTTPException(400, "Esse jogador já foi escolhido por outro time")
    if req.slotId not in card["valid_slots"]:
        raise HTTPException(400, "Posição inválida para este jogador")
    if team["squad"][req.slotId] is not None:
        raise HTTPException(400, "Posição já preenchida")
    team["squad"][req.slotId] = {
        "id": card["id"], "name": card["name"], "ovr": card["ovr"],
        "positions": card["positions"], "squad_label": card["squad_label"],
        "color": card["color"], "accent": card["accent"],
    }
    room["draftedPlayerNames"].add(card["name"])
    room["picksMade"] += 1
    await broadcast(code, "pick", {"team_id": team["id"], "slotId": req.slotId,
                                   "card": team["squad"][req.slotId]})
    advance_turn(room)
    await broadcast(code, "state")
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


# ----------------------------- League construction -----------------------------
def make_team_from_squad_label(label: str, formation: str, used_names: set) -> Optional[dict]:
    """Build an NPC team from a specific squad label.
    Slots are filled in priority order (most-specialised positions first) so the
    flexible CM/CAM slots don't steal away a unique ST/CB."""
    squad = get_squad_by_label(label)
    if not squad:
        return None
    slots = FORMATIONS[formation]
    candidates = sorted(
        [p for p in squad["players"] if p["name"] not in used_names],
        key=lambda x: -x["ovr"]
    )
    placement = {}
    placed_names = set()
    PRIORITY = {"GK": 0, "ST": 1, "CB": 2, "LB": 3, "RB": 3,
                "LW": 4, "RW": 4, "CAM": 5, "LM": 6, "RM": 6, "CDM": 7, "CM": 8}
    ordered_slots = sorted(slots, key=lambda s: PRIORITY.get(s["pos"], 9))
    for slot in ordered_slots:
        pick = None
        for p in candidates:
            if p["name"] in placed_names:
                continue
            if slot_accepts_player(slot["pos"], p["pos"]):
                pick = p
                break
        if not pick:
            return None
        placement[slot["id"]] = pick
        placed_names.add(pick["name"])

    team_squad = {sid: {
        "id": f"{squad['club']}-{squad['year']}-{p['name']}",
        "name": p["name"], "ovr": p["ovr"], "positions": p["pos"],
        "squad_label": squad["label"], "color": squad["color"], "accent": squad["accent"],
    } for sid, p in placement.items()}

    return {
        "label": squad["label"], "color": squad["color"], "accent": squad["accent"],
        "formation": formation, "squad": team_squad,
        "names": placed_names,
    }


def build_league_teams(room: dict) -> List[dict]:
    """Return a list of LEAGUE_SIZE league teams (humans first, then NPC fillers).
    Ensures no duplicate squad-label across teams. NPC teams cannot use any
    player NAME that a human already drafted; among NPCs name overlap is allowed
    so we don't run out of buildable squads."""
    league_teams = []
    used_labels = set()
    blocked_names_for_npc = set(room["draftedPlayerNames"])  # humans' picks lock these names out of NPCs

    for t in room["teams"]:
        league_teams.append({
            "id": t["id"], "teamName": t["teamName"], "isNpc": False,
            "country": "BRA",
            "color": "#39FF14", "accent": "#FFD700",
            "ovr": round(team_ovr(t["squad"]), 1),
            "squad": t["squad"], "formation": t["formation"],
            "label": None,
        })

    candidate_labels = [s["label"] for s in SQUADS if s["label"] not in used_labels]
    random.shuffle(candidate_labels)
    npc_idx = 0
    while len(league_teams) < LEAGUE_SIZE and candidate_labels:
        chosen = None
        for label in list(candidate_labels):
            built = make_team_from_squad_label(
                label, random.choice(list(FORMATIONS.keys())), blocked_names_for_npc
            )
            if built is None:
                continue
            chosen = built
            candidate_labels.remove(label)
            used_labels.add(label)
            break
        if not chosen:
            # Fallback: relax name uniqueness completely (avoid league size shortage)
            for label in list(candidate_labels):
                built = make_team_from_squad_label(label, "4-3-3", set())
                if built is None:
                    continue
                chosen = built
                candidate_labels.remove(label)
                used_labels.add(label)
                break
        if not chosen:
            log.warning("Could not build any more NPC teams; league might be short.")
            break
        sq = get_squad_by_label(chosen["label"])
        league_teams.append({
            "id": f"npc_{npc_idx}",
            "teamName": chosen["label"],
            "isNpc": True,
            "country": "BRA",
            "color": sq["color"], "accent": sq["accent"],
            "ovr": round(team_ovr(chosen["squad"]), 1),
            "squad": chosen["squad"], "formation": chosen["formation"],
            "label": chosen["label"],
        })
        npc_idx += 1

    # Ensure even count for fixture generator (drop last NPC if needed)
    if len(league_teams) % 2 == 1:
        league_teams = league_teams[:-1]
    random.shuffle(league_teams)
    return league_teams


def build_intl_teams(used_labels: set, used_names: set, count: int) -> List[dict]:
    """Build `count` international NPC teams (Libertadores / Sul-Americana fillers)."""
    out = []
    intl_pool = list(INTL_CLUBS)
    random.shuffle(intl_pool)
    label_pool = [s["label"] for s in SQUADS if s["label"] not in used_labels]
    random.shuffle(label_pool)
    for i in range(count):
        club_name, country, color = intl_pool[i % len(intl_pool)]
        built = None
        for label in list(label_pool):
            cand = make_team_from_squad_label(
                label, random.choice(list(FORMATIONS.keys())), used_names
            )
            if cand is None:
                continue
            built = cand
            label_pool.remove(label)
            used_labels.add(label)
            break
        if not built:
            # Relax name constraint
            for label in list(label_pool):
                cand = make_team_from_squad_label(label, "4-3-3", set())
                if cand is None:
                    continue
                built = cand
                label_pool.remove(label)
                used_labels.add(label)
                break
        if not built:
            break
        out.append({
            "id": f"intl_{country.lower()}_{i}_{random.randint(1000,9999)}",
            "teamName": club_name,
            "isNpc": True,
            "country": country,
            "color": color, "accent": "#FFFFFF",
            "ovr": round(team_ovr(built["squad"]), 1),
            "squad": built["squad"], "formation": built["formation"],
            "label": built["label"],
        })
    return out


# ----------------------------- Simulation helpers -----------------------------
def pick_scorer(team_obj):
    pool = []
    for p in team_obj["squad"].values():
        if p is None:
            continue
        pos = p.get("positions", [])
        weight = 1
        if "ST" in pos:
            weight = 8
        elif any(x in pos for x in ["LW", "RW", "CAM"]):
            weight = 5
        elif any(x in pos for x in ["CM", "LM", "RM"]):
            weight = 3
        elif any(x in pos for x in ["CB", "LB", "RB", "CDM"]):
            weight = 1
        if "GK" in pos:
            weight = 0
        pool.extend([p] * weight)
    return random.choice(pool) if pool else None


def make_match(sim_teams: dict, home_id: str, away_id: str,
               tie_id: Optional[str] = None, leg: Optional[int] = None,
               neutral: bool = False) -> dict:
    ht = sim_teams[home_id]
    at = sim_teams[away_id]
    home_form = random.uniform(-5, 5)
    away_form = random.uniform(-5, 5)
    # Neutral venues skip home advantage
    if neutral:
        ht_ovr, at_ovr = ht["ovr"], at["ovr"]
        hg, ag, events = simulate_match_goals(ht_ovr, at_ovr, home_form, away_form)
        # Strip home advantage by averaging — simple: reduce home goals slightly
    else:
        hg, ag, events = simulate_match_goals(ht["ovr"], at["ovr"], home_form, away_form)
    final_events = []
    for ev in events:
        if "flavor" not in ev:
            scorer = pick_scorer(ht if ev["team"] == "home" else at)
            final_events.append({**ev, "scorer": scorer["name"] if scorer else "?"})
        else:
            final_events.append(ev)
    return {
        "home_id": home_id, "away_id": away_id,
        "home_name": ht["teamName"], "away_name": at["teamName"],
        "home_color": ht["color"], "away_color": at["color"],
        "home_score": 0, "away_score": 0,
        "final_home": hg, "final_away": ag,
        "events": final_events,
        "emitted": [],
        "home_is_npc": ht["isNpc"], "away_is_npc": at["isNpc"],
        "tie_id": tie_id, "leg": leg, "neutral": neutral,
        "done": False,
    }


def apply_standings_after_match(standings: dict, m: dict):
    """Update league/group standings with this match's final score."""
    hs = standings[m["home_id"]]
    as_ = standings[m["away_id"]]
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


# ----------------------------- Competition builders -----------------------------
def make_league_comp(league_teams: list) -> dict:
    fixtures = generate_fixtures([t["id"] for t in league_teams])
    phases = []
    sim_teams = {t["id"]: t for t in league_teams}
    for r_idx, rd in enumerate(fixtures):
        matches = [make_match(sim_teams, h, a) for (h, a) in rd]
        phases.append({"name": f"Rodada {r_idx + 1}", "matches": matches})
    standings = {t["id"]: {"id": t["id"], "teamName": t["teamName"], "isNpc": t["isNpc"],
                            "ovr": t["ovr"], "P": 0, "W": 0, "D": 0, "L": 0,
                            "GF": 0, "GA": 0, "GD": 0, "Pts": 0}
                  for t in league_teams}
    return {
        "id": "league",
        "name": "Brasileirão Série A",
        "type": "league",
        "teamIds": [t["id"] for t in league_teams],
        "status": "ready",
        "currentPhaseIdx": -1,
        "phases": phases,
        "standings": standings,
        "winner_id": None,
    }


def make_copa_brasil_comp(sim_teams: dict, league_team_ids: List[str]) -> dict:
    """Round of 16 -> QF -> SF (2 legs) -> Final (2 legs). Random draw from league teams."""
    qualifying = random.sample(league_team_ids, COPA_BRASIL_SIZE)
    random.shuffle(qualifying)
    r16_matches = []
    for i in range(0, COPA_BRASIL_SIZE, 2):
        h, a = qualifying[i], qualifying[i + 1]
        r16_matches.append(make_match(sim_teams, h, a))
    phases = [
        {"name": "Oitavas de Final", "matches": r16_matches},
        # subsequent phases generated dynamically after winners decided
    ]
    bracket = {
        "stages": [
            {"name": "Oitavas", "matchups": [(m["home_id"], m["away_id"], None) for m in r16_matches]},
        ]
    }
    return {
        "id": "copa_brasil",
        "name": "Copa do Brasil",
        "type": "knockout",
        "teamIds": qualifying,
        "status": "ready",
        "currentPhaseIdx": -1,
        "phases": phases,
        "winner_id": None,
        "bracket": bracket,
        "ties": {},  # tie_id -> dict for 2-leg ties (SF / Final)
    }


def make_cup_comp(sim_teams: dict, brazilian_ids: List[str], intl_ids: List[str],
                   cup_id: str, cup_name: str) -> dict:
    """Libertadores / Sul-Americana: 8 teams in 2 groups, then SF (2 legs), then Final (1 leg neutral)."""
    all_ids = brazilian_ids + intl_ids
    random.shuffle(all_ids)
    group_a = all_ids[:4]
    group_b = all_ids[4:]
    # Three rounds of single-leg fixtures per group.
    def gen_group_rounds(group):
        n = 4
        teams_local = list(group)
        rounds = []
        for r in range(n - 1):
            rmatches = []
            for i in range(n // 2):
                h, a = teams_local[i], teams_local[n - 1 - i]
                if r % 2 == 1:
                    h, a = a, h
                rmatches.append((h, a))
            rounds.append(rmatches)
            teams_local = [teams_local[0]] + [teams_local[-1]] + teams_local[1:-1]
        return rounds  # list of 3 rounds; each round has 2 matches

    a_rounds = gen_group_rounds(group_a)
    b_rounds = gen_group_rounds(group_b)
    phases = []
    for ri in range(3):
        matches_a = [make_match(sim_teams, h, a) for (h, a) in a_rounds[ri]]
        matches_b = [make_match(sim_teams, h, a) for (h, a) in b_rounds[ri]]
        phases.append({"name": f"Fase de Grupos – Rodada {ri + 1}",
                        "matches": matches_a + matches_b})
    standings = {tid: {"id": tid, "teamName": sim_teams[tid]["teamName"], "isNpc": sim_teams[tid]["isNpc"],
                        "ovr": sim_teams[tid]["ovr"], "country": sim_teams[tid]["country"],
                        "P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "GD": 0, "Pts": 0,
                        "group": "A" if tid in group_a else "B"}
                  for tid in all_ids}
    return {
        "id": cup_id,
        "name": cup_name,
        "type": "groups_knockout",
        "teamIds": all_ids,
        "status": "ready",
        "currentPhaseIdx": -1,
        "phases": phases,
        "standings": standings,
        "groups": {"A": group_a, "B": group_b},
        "winner_id": None,
        "ties": {},
    }


# ----------------------------- Knockout helpers -----------------------------
def tie_winner(tie: dict) -> str:
    """Return winning team id of a 2-leg tie."""
    a, b = tie["team_a_id"], tie["team_b_id"]
    agg_a = tie["agg_a"]
    agg_b = tie["agg_b"]
    if agg_a > agg_b:
        return a
    if agg_b > agg_a:
        return b
    # Away goals: a played leg2 as away (its leg2 score = a away goals),
    # b played leg1 as away.
    away_a = tie.get("a_away_goals", 0)
    away_b = tie.get("b_away_goals", 0)
    if away_a > away_b:
        return a
    if away_b > away_a:
        return b
    return random.choice([a, b])


def update_tie_after_leg(tie: dict, m: dict):
    """Record the match result into the tie aggregate."""
    a = tie["team_a_id"]
    if m["home_id"] == a:
        # leg1: a home, b away
        tie["agg_a"] += m["home_score"]
        tie["agg_b"] += m["away_score"]
        tie["b_away_goals"] = tie.get("b_away_goals", 0) + m["away_score"]
    else:
        # m["home_id"] == b -> leg2: b home, a away
        tie["agg_b"] += m["home_score"]
        tie["agg_a"] += m["away_score"]
        tie["a_away_goals"] = tie.get("a_away_goals", 0) + m["away_score"]


# ----------------------------- Phase advancement -----------------------------
def build_next_knockout_phase(comp: dict, sim_teams: dict):
    """After current phase finished, build the next phase. Mutates comp."""
    cid = comp["id"]
    cur_idx = comp["currentPhaseIdx"]
    cur_phase = comp["phases"][cur_idx]
    # Get winners from cur_phase
    if cid == "copa_brasil":
        if cur_phase["name"] == "Oitavas de Final":
            winners = [m["home_id"] if m["home_score"] > m["away_score"]
                        else (m["away_id"] if m["away_score"] > m["home_score"]
                              else random.choice([m["home_id"], m["away_id"]]))
                        for m in cur_phase["matches"]]
            qf_matches = [make_match(sim_teams, winners[i], winners[i + 1])
                          for i in range(0, len(winners), 2)]
            comp["phases"].append({"name": "Quartas de Final", "matches": qf_matches})
            comp["bracket"]["stages"].append({"name": "Quartas",
                                              "matchups": [(m["home_id"], m["away_id"], None) for m in qf_matches]})
            return
        if cur_phase["name"] == "Quartas de Final":
            winners = [m["home_id"] if m["home_score"] > m["away_score"]
                        else (m["away_id"] if m["away_score"] > m["home_score"]
                              else random.choice([m["home_id"], m["away_id"]]))
                        for m in cur_phase["matches"]]
            sf_l1 = []
            for i in range(0, len(winners), 2):
                a, b = winners[i], winners[i + 1]
                tie_id = f"sf_{i // 2}"
                comp["ties"][tie_id] = {"tie_id": tie_id, "team_a_id": a, "team_b_id": b,
                                          "agg_a": 0, "agg_b": 0,
                                          "a_away_goals": 0, "b_away_goals": 0, "winner_id": None}
                sf_l1.append(make_match(sim_teams, a, b, tie_id=tie_id, leg=1))
            comp["phases"].append({"name": "Semifinal — Ida", "matches": sf_l1})
            comp["bracket"]["stages"].append({"name": "Semifinal Ida",
                                              "matchups": [(m["home_id"], m["away_id"], m["tie_id"]) for m in sf_l1]})
            return
        if cur_phase["name"] == "Semifinal — Ida":
            sf_l2 = []
            for m in cur_phase["matches"]:
                tie_id = m["tie_id"]
                tie = comp["ties"][tie_id]
                # leg2 reverses: b home, a away
                sf_l2.append(make_match(sim_teams, tie["team_b_id"], tie["team_a_id"],
                                          tie_id=tie_id, leg=2))
            comp["phases"].append({"name": "Semifinal — Volta", "matches": sf_l2})
            comp["bracket"]["stages"].append({"name": "Semifinal Volta",
                                              "matchups": [(m["home_id"], m["away_id"], m["tie_id"]) for m in sf_l2]})
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
            comp["ties"][tie_id] = {"tie_id": tie_id, "team_a_id": a, "team_b_id": b,
                                      "agg_a": 0, "agg_b": 0,
                                      "a_away_goals": 0, "b_away_goals": 0, "winner_id": None}
            f_l1.append(make_match(sim_teams, a, b, tie_id=tie_id, leg=1))
            comp["phases"].append({"name": "Final — Ida", "matches": f_l1})
            comp["bracket"]["stages"].append({"name": "Final Ida",
                                              "matchups": [(m["home_id"], m["away_id"], m["tie_id"]) for m in f_l1]})
            return
        if cur_phase["name"] == "Final — Ida":
            m = cur_phase["matches"][0]
            tie = comp["ties"][m["tie_id"]]
            f_l2 = [make_match(sim_teams, tie["team_b_id"], tie["team_a_id"],
                                 tie_id=m["tie_id"], leg=2)]
            comp["phases"].append({"name": "Final — Volta", "matches": f_l2})
            comp["bracket"]["stages"].append({"name": "Final Volta",
                                              "matchups": [(mm["home_id"], mm["away_id"], mm["tie_id"]) for mm in f_l2]})
            return
        if cur_phase["name"] == "Final — Volta":
            # Determine champion
            tie = comp["ties"]["final_0"]
            comp["winner_id"] = tie_winner(tie)
            return  # no further phase
    elif cid in ("libertadores", "sulamericana"):
        # 3 group rounds already in phases. After phase index 2 (third group round), build SF.
        if comp["currentPhaseIdx"] == 2:
            # Top 2 of each group qualify
            standings = comp["standings"]
            groups = comp["groups"]
            def rank(group_ids):
                return sorted([standings[tid] for tid in group_ids],
                                key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))
            a_rank = rank(groups["A"])
            b_rank = rank(groups["B"])
            sf_l1 = []
            # 1A vs 2B and 1B vs 2A
            pairs = [(a_rank[0]["id"], b_rank[1]["id"]), (b_rank[0]["id"], a_rank[1]["id"])]
            for idx, (a, b) in enumerate(pairs):
                tie_id = f"libsf_{idx}"
                comp["ties"][tie_id] = {"tie_id": tie_id, "team_a_id": a, "team_b_id": b,
                                          "agg_a": 0, "agg_b": 0,
                                          "a_away_goals": 0, "b_away_goals": 0, "winner_id": None}
                sf_l1.append(make_match(sim_teams, a, b, tie_id=tie_id, leg=1))
            comp["phases"].append({"name": "Semifinal — Ida", "matches": sf_l1})
            return
        cur_name = cur_phase["name"]
        if cur_name == "Semifinal — Ida":
            sf_l2 = []
            for m in cur_phase["matches"]:
                tid = m["tie_id"]
                tie = comp["ties"][tid]
                sf_l2.append(make_match(sim_teams, tie["team_b_id"], tie["team_a_id"],
                                          tie_id=tid, leg=2))
            comp["phases"].append({"name": "Semifinal — Volta", "matches": sf_l2})
            return
        if cur_name == "Semifinal — Volta":
            winners = []
            for tid, tie in comp["ties"].items():
                if tid.startswith("libsf_"):
                    tie["winner_id"] = tie_winner(tie)
                    winners.append(tie["winner_id"])
            # Final single neutral match
            final = [make_match(sim_teams, winners[0], winners[1], neutral=True)]
            comp["phases"].append({"name": "Final (Jogo Único)", "matches": final})
            return
        if cur_name == "Final (Jogo Único)":
            m = cur_phase["matches"][0]
            if m["home_score"] > m["away_score"]:
                comp["winner_id"] = m["home_id"]
            elif m["away_score"] > m["home_score"]:
                comp["winner_id"] = m["away_id"]
            else:
                comp["winner_id"] = random.choice([m["home_id"], m["away_id"]])
            return


# ----------------------------- Simulation loop -----------------------------
async def simulate_phase(code: str, comp_id: str):
    """Tick through the current phase of a given competition until minute 90.
    Updates standings live (after each match's final goal/end). Then sets status to round_break."""
    room = ROOMS[code]
    sim = room["sim"]
    comp = sim["competitions"][comp_id]
    phase = comp["phases"][comp["currentPhaseIdx"]]
    matches = phase["matches"]
    sim["currentMatches"] = matches
    sim["currentMinute"] = 0
    comp["status"] = "playing"
    await broadcast(code, "state")
    await broadcast(code, "round_start", {"comp_id": comp_id,
                                            "phaseIdx": comp["currentPhaseIdx"],
                                            "phaseName": phase["name"],
                                            "matches": matches})
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
                    if ev["team"] == "home":
                        m["home_score"] += 1
                    else:
                        m["away_score"] += 1
                m["emitted"].append(ev)
                tick_events.append({"match_idx": m_idx, "event": ev,
                                     "home_id": m["home_id"], "away_id": m["away_id"]})
        await broadcast(code, "tick", {"comp_id": comp_id, "minute": minute,
                                         "events": tick_events,
                                         "scores": [(m["home_score"], m["away_score"]) for m in matches]})

    # Phase finished: apply results
    for m in matches:
        m["done"] = True
        # Update league/group standings if applicable
        if comp.get("standings") and m["home_id"] in comp["standings"]:
            apply_standings_after_match(comp["standings"], m)
        # Update tie aggregate
        if m.get("tie_id"):
            tie = comp["ties"].get(m["tie_id"])
            if tie:
                update_tie_after_leg(tie, m)
    # Build the next knockout phase if needed
    if comp["type"] in ("knockout", "groups_knockout"):
        build_next_knockout_phase(comp, sim["teams"])
    # Determine if competition completed
    is_last_phase = comp["currentPhaseIdx"] + 1 >= len(comp["phases"])
    if comp["type"] == "league" and is_last_phase:
        # Crown league champion: top of standings
        sorted_st = sorted(comp["standings"].values(),
                              key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))
        comp["winner_id"] = sorted_st[0]["id"]
        comp["status"] = "completed"
    elif comp["type"] in ("knockout", "groups_knockout"):
        if comp.get("winner_id"):
            comp["status"] = "completed"
        else:
            comp["status"] = "round_break"
    else:
        comp["status"] = "round_break"

    await broadcast(code, "round_end", {"comp_id": comp_id,
                                         "phaseIdx": comp["currentPhaseIdx"],
                                         "standings": list((comp.get("standings") or {}).values()),
                                         "winner_id": comp.get("winner_id")})
    # If this comp completed, advance to next comp (auto)
    if comp["status"] == "completed":
        advance_to_next_competition(room)
    await broadcast(code, "state")


def advance_to_next_competition(room: dict):
    sim = room["sim"]
    order = ["league", "copa_brasil", "libertadores", "sulamericana"]
    cur = sim["active"]
    cur_idx = order.index(cur) if cur in order else len(order)
    # If just finished league, initialise cups now using final standings
    if cur == "league":
        league = sim["competitions"]["league"]
        standings = sorted(league["standings"].values(),
                              key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))
        # Libertadores: top 4 brazilian + 4 intl
        top4 = [s["id"] for s in standings[:4]]
        five_eight = [s["id"] for s in standings[4:8]]
        used_labels = set()
        used_names = set()
        for t in sim["teams"].values():
            if t.get("label"):
                used_labels.add(t["label"])
            for p in t["squad"].values():
                if p:
                    used_names.add(p["name"])
        intl_lib = build_intl_teams(used_labels, used_names, 4)
        intl_sul = build_intl_teams(used_labels, used_names, 4)
        # Register intl teams in sim["teams"]
        for t in intl_lib + intl_sul:
            sim["teams"][t["id"]] = t
        lib = make_cup_comp(sim["teams"], top4, [t["id"] for t in intl_lib],
                              "libertadores", "Copa Libertadores")
        sul = make_cup_comp(sim["teams"], five_eight, [t["id"] for t in intl_sul],
                              "sulamericana", "Copa Sul-Americana")
        copa = make_copa_brasil_comp(sim["teams"], list(league["standings"].keys()))
        sim["competitions"]["copa_brasil"] = copa
        sim["competitions"]["libertadores"] = lib
        sim["competitions"]["sulamericana"] = sul
    # Find next not-completed competition
    next_id = None
    for cid in order[cur_idx + 1:]:
        if cid in sim["competitions"] and sim["competitions"][cid]["status"] != "completed":
            next_id = cid
            break
    if next_id:
        sim["active"] = next_id
        sim["competitions"][next_id]["status"] = "ready"
    else:
        sim["active"] = "completed"
        room["status"] = "finished"


# ----------------------------- Sim endpoints -----------------------------
@api.post("/rooms/{code}/start-sim")
async def start_sim(code: str, req: HostUpdateReq):
    room = ROOMS.get(code.upper())
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]:
        raise HTTPException(403, "Somente o anfitrião pode iniciar")
    if room["status"] != "ready_to_sim":
        raise HTTPException(400, f"Estado inválido: {room['status']}")
    league_teams = build_league_teams(room)
    sim_teams_dict = {t["id"]: t for t in league_teams}
    league_comp = make_league_comp(league_teams)
    sim = {
        "active": "league",
        "teams": sim_teams_dict,
        "competitions": {"league": league_comp},
        "currentMinute": 0,
        "currentMatches": [],
    }
    room["sim"] = sim
    room["status"] = "simulating"
    await broadcast(code, "state")
    return {"ok": True}


@api.post("/rooms/{code}/next-round")
async def next_round_endpoint(code: str, req: HostUpdateReq):
    code = code.upper()
    room = ROOMS.get(code)
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]:
        raise HTTPException(403, "Somente o anfitrião pode avançar")
    if room["status"] not in ("simulating",):
        raise HTTPException(400, "A temporada não está em andamento")
    sim = room["sim"]
    active = sim["active"]
    if active == "completed":
        raise HTTPException(400, "Temporada finalizada")
    comp = sim["competitions"].get(active)
    if not comp:
        raise HTTPException(400, "Competição inexistente")
    if comp["status"] == "playing":
        raise HTTPException(400, "Rodada em andamento")
    if comp["status"] not in ("ready", "round_break"):
        raise HTTPException(400, f"Estado inválido: {comp['status']}")
    # Advance phase
    comp["currentPhaseIdx"] += 1
    if comp["currentPhaseIdx"] >= len(comp["phases"]):
        raise HTTPException(400, "Sem fases pendentes")
    # Launch sim
    if code in SIM_TASKS and not SIM_TASKS[code].done():
        raise HTTPException(400, "Outra simulação em curso")
    SIM_TASKS[code] = asyncio.create_task(simulate_phase(code, active))
    return {"ok": True}


@api.post("/rooms/{code}/switch-competition")
async def switch_competition(code: str, req: HostUpdateReq):
    """Allow host to manually switch the active competition (only between completed-or-current ones)."""
    code = code.upper()
    room = ROOMS.get(code)
    if not room or not room.get("sim"):
        raise HTTPException(404, "Sala/simulação não encontrada")
    # This endpoint is more for the tab nav: the user clicking a tab shouldn't change
    # simulation state. We keep "active" only for which competition is up next to play.
    # No-op for now.
    return {"ok": True}


@api.post("/rooms/{code}/restart")
async def restart_room(code: str, req: HostUpdateReq):
    code = code.upper()
    room = ROOMS.get(code)
    if not room:
        raise HTTPException(404, "Sala não encontrada")
    if req.playerId != room["hostId"]:
        raise HTTPException(403, "Somente o anfitrião pode reiniciar")
    if room["status"] not in ("finished", "ready_to_sim", "simulating"):
        raise HTTPException(400, "Só é possível reiniciar após o término")
    # Cancel any running sim task
    if code in SIM_TASKS and not SIM_TASKS[code].done():
        SIM_TASKS[code].cancel()
    # Reset state: keep teams & names, wipe squads/draft/sim
    for t in room["teams"]:
        t["squad"] = empty_squad(t["formation"])
    room["status"] = "lobby"
    room["draftOrder"] = []
    room["currentTurnIdx"] = 0
    room["pickRound"] = 0
    room["picksMade"] = 0
    room["draftedPlayerNames"] = set()
    room["assignedClub"] = None
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
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown():
    for t in SIM_TASKS.values():
        t.cancel()
