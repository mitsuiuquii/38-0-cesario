"""Formation slot definitions + match simulation engine."""
import random
import math

# Each formation lists 11 slots with id, required position, and pitch coordinates (x=0-100, y=0-100)
# y=0 is top (away goal), y=100 is bottom (own goal)
FORMATIONS = {
    "4-3-3": [
        {"id": "GK",  "pos": "GK",  "x": 50, "y": 92},
        {"id": "LB",  "pos": "LB",  "x": 12, "y": 72},
        {"id": "CB1", "pos": "CB",  "x": 36, "y": 78},
        {"id": "CB2", "pos": "CB",  "x": 64, "y": 78},
        {"id": "RB",  "pos": "RB",  "x": 88, "y": 72},
        {"id": "CM1", "pos": "CM",  "x": 28, "y": 52},
        {"id": "CAM", "pos": "CAM", "x": 50, "y": 40},
        {"id": "CM2", "pos": "CM",  "x": 72, "y": 52},
        {"id": "LW",  "pos": "LW",  "x": 15, "y": 22},
        {"id": "ST",  "pos": "ST",  "x": 50, "y": 14},
        {"id": "RW",  "pos": "RW",  "x": 85, "y": 22},
    ],
    "4-4-2": [
        {"id": "GK",  "pos": "GK",  "x": 50, "y": 92},
        {"id": "LB",  "pos": "LB",  "x": 12, "y": 72},
        {"id": "CB1", "pos": "CB",  "x": 36, "y": 78},
        {"id": "CB2", "pos": "CB",  "x": 64, "y": 78},
        {"id": "RB",  "pos": "RB",  "x": 88, "y": 72},
        {"id": "LM",  "pos": "LM",  "x": 14, "y": 46},
        {"id": "CM1", "pos": "CM",  "x": 36, "y": 50},
        {"id": "CM2", "pos": "CM",  "x": 64, "y": 50},
        {"id": "RM",  "pos": "RM",  "x": 86, "y": 46},
        {"id": "ST1", "pos": "ST",  "x": 36, "y": 18},
        {"id": "ST2", "pos": "ST",  "x": 64, "y": 18},
    ],
    "3-5-2": [
        {"id": "GK",  "pos": "GK",  "x": 50, "y": 92},
        {"id": "CB1", "pos": "CB",  "x": 22, "y": 78},
        {"id": "CB2", "pos": "CB",  "x": 50, "y": 80},
        {"id": "CB3", "pos": "CB",  "x": 78, "y": 78},
        {"id": "LM",  "pos": "LM",  "x": 10, "y": 50},
        {"id": "CM1", "pos": "CM",  "x": 32, "y": 55},
        {"id": "CAM", "pos": "CAM", "x": 50, "y": 40},
        {"id": "CM2", "pos": "CM",  "x": 68, "y": 55},
        {"id": "RM",  "pos": "RM",  "x": 90, "y": 50},
        {"id": "ST1", "pos": "ST",  "x": 36, "y": 16},
        {"id": "ST2", "pos": "ST",  "x": 64, "y": 16},
    ],
    "4-2-3-1": [
        {"id": "GK",   "pos": "GK",   "x": 50, "y": 92},
        {"id": "LB",   "pos": "LB",   "x": 12, "y": 72},
        {"id": "CB1",  "pos": "CB",   "x": 36, "y": 78},
        {"id": "CB2",  "pos": "CB",   "x": 64, "y": 78},
        {"id": "RB",   "pos": "RB",   "x": 88, "y": 72},
        {"id": "CDM1", "pos": "CDM",  "x": 36, "y": 58},
        {"id": "CDM2", "pos": "CDM",  "x": 64, "y": 58},
        {"id": "CAM",  "pos": "CAM",  "x": 50, "y": 36},
        {"id": "LW",   "pos": "LW",   "x": 14, "y": 28},
        {"id": "RW",   "pos": "RW",   "x": 86, "y": 28},
        {"id": "ST",   "pos": "ST",   "x": 50, "y": 12},
    ],
}


def slot_accepts_player(slot_pos: str, player_positions: list) -> bool:
    """Strict rule with sensible flexibility:
    - GK only fits GK.
    - LM can be filled by LM or LW; RM by RM or RW (and vice-versa is also allowed
      since wide players are interchangeable in Brazilian football culture).
    - CM accepts CM, CDM, CAM.
    - CDM accepts CDM or CM.
    - CAM accepts CAM or CM.
    - LW/RW accept LW/RW/LM/RM.
    """
    if slot_pos == "GK":
        return "GK" in player_positions
    if "GK" in player_positions:
        return False  # GKs never play outfield

    if slot_pos in player_positions:
        return True

    equivalents = {
        "LM": {"LW"},
        "RM": {"RW"},
        "LW": {"LM"},
        "RW": {"RM"},
        "CM": {"CDM", "CAM"},
        "CDM": {"CM"},
        "CAM": {"CM"},
    }
    return any(p in equivalents.get(slot_pos, set()) for p in player_positions)


def poisson(lam: float) -> int:
    """Generate a Poisson-distributed integer."""
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p <= L:
            return k - 1


def simulate_match_goals(home_ovr: float, away_ovr: float, home_form: float, away_form: float):
    """Return (home_goals, away_goals, goal_events).
    goal_events is a list of dicts: {minute, team, scorer_idx}.
    """
    home_eff = home_ovr + home_form + 2.5  # home advantage
    away_eff = away_ovr + away_form

    diff = (home_eff - away_eff) / 12.0  # normalised
    home_lambda = max(0.25, 1.45 + diff * 1.1)
    away_lambda = max(0.20, 1.25 - diff * 1.1)

    home_goals = poisson(home_lambda)
    away_goals = poisson(away_lambda)

    events = []
    for _ in range(home_goals):
        events.append({"minute": random.randint(1, 90), "team": "home"})
    for _ in range(away_goals):
        events.append({"minute": random.randint(1, 90), "team": "away"})
    events.sort(key=lambda e: e["minute"])

    # Flavor events (yellow cards / saves / near misses)
    flavor_types = ["yellow", "save", "near_miss"]
    for _ in range(random.randint(2, 5)):
        events.append({
            "minute": random.randint(5, 89),
            "team": random.choice(["home", "away"]),
            "flavor": random.choice(flavor_types),
        })
    events.sort(key=lambda e: e["minute"])

    return home_goals, away_goals, events


def team_ovr(squad: dict) -> float:
    """squad is dict slot_id -> player_obj (or None). Return avg OVR of 11."""
    vals = [p["ovr"] for p in squad.values() if p is not None]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def generate_fixtures(team_ids: list):
    """Round-robin double-leg fixtures. For N teams (even), 2*(N-1) rounds.
    Returns list of rounds; each round = list of (home_id, away_id)."""
    n = len(team_ids)
    assert n % 2 == 0, "team count must be even"
    teams = list(team_ids)
    rounds = []
    # First half
    for r in range(n - 1):
        round_matches = []
        for i in range(n // 2):
            h, a = teams[i], teams[n - 1 - i]
            # alternate home/away per round to balance
            if r % 2 == 1:
                h, a = a, h
            round_matches.append((h, a))
        rounds.append(round_matches)
        # rotate (keep first fixed)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    # Second half = reverse home/away of first half
    second = []
    for rd in rounds:
        second.append([(a, h) for (h, a) in rd])
    return rounds + second


def pick_random_npc_squad(squad_pool: list, used_player_ids: set, slots: list):
    """Build a valid 11-player NPC team from a single historical squad.
    Returns dict slot_id -> player or None if impossible (skip).
    Accepts both raw squad players ({name,pos,ovr}) and enriched players ({id,positions})."""
    def _pid(p):
        return p.get("id") or p.get("name")
    def _positions(p):
        return p.get("positions") if "positions" in p else p.get("pos", [])
    available = [p for p in squad_pool if _pid(p) not in used_player_ids]
    team = {}
    # Sort slots so GK first then defensive then attacking
    order = sorted(slots, key=lambda s: 0 if s["pos"] == "GK" else 1)
    used_local = set()
    for slot in order:
        candidates = [p for p in available
                      if _pid(p) not in used_local and slot_accepts_player(slot["pos"], _positions(p))]
        if not candidates:
            return None
        chosen = random.choice(candidates)
        team[slot["id"]] = chosen
        used_local.add(_pid(chosen))
    return team
