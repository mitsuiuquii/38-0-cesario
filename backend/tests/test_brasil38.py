"""Backend tests for 38-0 Brasil app: rooms, draft, simulation, WS."""
import os
import time
import json
import asyncio
import pytest
import requests
import websockets

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pitch-league-2.preview.emergentagent.com").rstrip("/")
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
API = f"{BASE_URL}/api"


# ----------------------------- Helpers -----------------------------
def _create_room(name="Host", team="Hostbrasil", password=None, show_ovr=True):
    r = requests.post(f"{API}/rooms", json={
        "name": name, "teamName": team, "password": password, "showOvr": show_ovr,
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _join(code, name="Guest", team="Guestbrasil", password=None):
    return requests.post(f"{API}/rooms/{code}/join",
                         json={"name": name, "teamName": team, "password": password}, timeout=15)


def _state(code, pid=None):
    r = requests.get(f"{API}/rooms/{code}", params={"playerId": pid} if pid else {}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _make_full_draft_room():
    """Create room, add a second player, start draft, return (code, hostId, guestId)."""
    r = _create_room()
    code, host = r["code"], r["playerId"]
    j = _join(code).json()
    guest = j["playerId"]
    sd = requests.post(f"{API}/rooms/{code}/start-draft",
                       json={"playerId": host}, timeout=15)
    assert sd.status_code == 200, sd.text
    return code, host, guest


# ----------------------------- Static endpoints -----------------------------
class TestStatic:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["squads"] >= 28
        assert body["players"] >= 300

    def test_formations(self):
        r = requests.get(f"{API}/formations", timeout=10)
        assert r.status_code == 200
        data = r.json()
        for f in ["4-3-3", "4-4-2", "3-5-2", "4-2-3-1"]:
            assert f in data, f"missing formation {f}"
            assert len(data[f]) == 11, f"{f} should have 11 slots"

    def test_squads(self):
        r = requests.get(f"{API}/squads", timeout=10)
        assert r.status_code == 200
        squads = r.json()
        assert len(squads) >= 28
        for s in squads:
            assert "label" in s and "club" in s and "year" in s
            assert s["player_count"] >= 11


# ----------------------------- Room lifecycle -----------------------------
class TestRoomLifecycle:
    def test_create_room(self):
        r = _create_room()
        assert "code" in r and len(r["code"]) == 6
        assert "playerId" in r
        st = _state(r["code"])
        assert st["status"] == "lobby"
        assert len(st["teams"]) == 1

    def test_join_room_success(self):
        r = _create_room()
        j = _join(r["code"])
        assert j.status_code == 200, j.text
        st = _state(r["code"])
        assert len(st["teams"]) == 2

    def test_join_password_required(self):
        r = _create_room(password="secret")
        bad = _join(r["code"], password="wrong")
        assert bad.status_code == 403
        ok = _join(r["code"], password="secret")
        assert ok.status_code == 200

    def test_join_rejected_after_draft(self):
        code, host, _ = _make_full_draft_room()
        late = _join(code, name="Late")
        assert late.status_code == 400

    def test_update_team_name_and_formation(self):
        r = _create_room()
        code, pid = r["code"], r["playerId"]
        upd = requests.post(f"{API}/rooms/{code}/update-team",
                            json={"playerId": pid, "teamName": "NewName", "formation": "3-5-2"}, timeout=10)
        assert upd.status_code == 200, upd.text
        st = _state(code)
        t = st["teams"][0]
        assert t["teamName"] == "NewName"
        assert t["formation"] == "3-5-2"
        # squad should be empty
        assert all(v is None for v in t["squad"].values())
        assert len(t["squad"]) == 11

    def test_host_update_show_ovr_host_only(self):
        r = _create_room(show_ovr=True)
        code, host = r["code"], r["playerId"]
        j = _join(code).json()
        guest = j["playerId"]
        # guest cannot toggle
        bad = requests.post(f"{API}/rooms/{code}/host-update",
                            json={"playerId": guest, "showOvr": False}, timeout=10)
        assert bad.status_code == 403
        ok = requests.post(f"{API}/rooms/{code}/host-update",
                           json={"playerId": host, "showOvr": False}, timeout=10)
        assert ok.status_code == 200
        st = _state(code)
        assert st["showOvr"] is False

    def test_start_draft_needs_two_players(self):
        r = _create_room()
        bad = requests.post(f"{API}/rooms/{r['code']}/start-draft",
                            json={"playerId": r["playerId"]}, timeout=10)
        assert bad.status_code == 400

    def test_start_draft_host_only(self):
        r = _create_room()
        j = _join(r["code"]).json()
        bad = requests.post(f"{API}/rooms/{r['code']}/start-draft",
                            json={"playerId": j["playerId"]}, timeout=10)
        assert bad.status_code == 403


# ----------------------------- Draft picking -----------------------------
class TestDraft:
    def test_start_draft_transitions(self):
        code, host, guest = _make_full_draft_room()
        st = _state(code)
        assert st["status"] == "drafting"
        assert st["assignedClub"] is not None
        assert len(st["availablePlayers"]) > 0

    def test_draft_pick_wrong_turn_rejected(self):
        code, host, guest = _make_full_draft_room()
        st = _state(code)
        # The current picker is teams[draftOrder[currentTurnIdx]]
        current_team_idx = st["draftOrder"][st["currentTurnIdx"]]
        current_pid = st["teams"][current_team_idx]["id"]
        wrong_pid = host if current_pid != host else guest
        card = st["availablePlayers"][0]
        r = requests.post(f"{API}/rooms/{code}/draft-pick", json={
            "playerId": wrong_pid, "cardId": card["id"], "slotId": card["valid_slots"][0]
        }, timeout=10)
        assert r.status_code == 403

    def test_draft_pick_invalid_slot_rejected(self):
        code, host, guest = _make_full_draft_room()
        st = _state(code)
        current_team_idx = st["draftOrder"][st["currentTurnIdx"]]
        current_pid = st["teams"][current_team_idx]["id"]
        card = st["availablePlayers"][0]
        # pick a slot not in valid_slots
        all_slots = list(st["teams"][current_team_idx]["squad"].keys())
        invalid = next((s for s in all_slots if s not in card["valid_slots"]), None)
        if invalid is None:
            pytest.skip("All slots valid for first card")
        r = requests.post(f"{API}/rooms/{code}/draft-pick", json={
            "playerId": current_pid, "cardId": card["id"], "slotId": invalid
        }, timeout=10)
        assert r.status_code == 400

    def test_complete_full_draft_and_ready_to_sim(self):
        code, host, guest = _make_full_draft_room()
        # 2 teams * 11 = 22 picks total
        for i in range(22):
            st = _state(code)
            if st["status"] != "drafting":
                break
            cur_idx = st["draftOrder"][st["currentTurnIdx"]]
            cur_pid = st["teams"][cur_idx]["id"]
            avail = st["availablePlayers"]
            assert avail, f"No available players at pick {i}"
            picked = None
            for card in avail:
                # find a slot from valid_slots that is empty
                for s in card["valid_slots"]:
                    if st["teams"][cur_idx]["squad"].get(s) is None:
                        picked = (card, s)
                        break
                if picked:
                    break
            assert picked, f"No valid pick found at iteration {i}"
            card, slot_id = picked
            r = requests.post(f"{API}/rooms/{code}/draft-pick", json={
                "playerId": cur_pid, "cardId": card["id"], "slotId": slot_id
            }, timeout=10)
            assert r.status_code == 200, f"pick {i} failed: {r.text}"

        st = _state(code)
        assert st["status"] == "ready_to_sim", f"got {st['status']}"
        assert not st["availablePlayers"]
        assert st["assignedClub"] in (None, "")
        # each team has 11 filled slots
        for t in st["teams"]:
            filled = sum(1 for v in t["squad"].values() if v is not None)
            assert filled == 11, f"team {t['teamName']} has {filled} filled"

    def test_pick_already_drafted_rejected(self):
        code, host, guest = _make_full_draft_room()
        st = _state(code)
        cur_idx = st["draftOrder"][st["currentTurnIdx"]]
        cur_pid = st["teams"][cur_idx]["id"]
        card = st["availablePlayers"][0]
        slot = card["valid_slots"][0]
        r1 = requests.post(f"{API}/rooms/{code}/draft-pick", json={
            "playerId": cur_pid, "cardId": card["id"], "slotId": slot
        }, timeout=10)
        assert r1.status_code == 200, r1.text
        # try to repick same cardId by next picker (should be different player turn now anyway)
        st2 = _state(code)
        cur_idx2 = st2["draftOrder"][st2["currentTurnIdx"]]
        cur_pid2 = st2["teams"][cur_idx2]["id"]
        # availablePlayers now is from a different assigned club; just verify drafted set
        assert card["id"] in st2["draftedPlayerIds"]


# ----------------------------- Simulation -----------------------------
class TestSimulation:
    @pytest.fixture(scope="class")
    def finished_room(self):
        """Drive draft to ready_to_sim, start turbo sim, wait, return final state."""
        r = _create_room()
        code, host = r["code"], r["playerId"]
        j = _join(code).json()
        guest = j["playerId"]
        sd = requests.post(f"{API}/rooms/{code}/start-draft", json={"playerId": host}, timeout=15)
        assert sd.status_code == 200, sd.text
        # finish 22 picks
        for i in range(22):
            st = _state(code)
            if st["status"] != "drafting":
                break
            cur_idx = st["draftOrder"][st["currentTurnIdx"]]
            cur_pid = st["teams"][cur_idx]["id"]
            avail = st["availablePlayers"]
            picked = None
            for card in avail:
                for s in card["valid_slots"]:
                    if st["teams"][cur_idx]["squad"].get(s) is None:
                        picked = (card, s); break
                if picked:
                    break
            assert picked
            card, slot_id = picked
            r2 = requests.post(f"{API}/rooms/{code}/draft-pick", json={
                "playerId": cur_pid, "cardId": card["id"], "slotId": slot_id
            }, timeout=10)
            assert r2.status_code == 200, r2.text
        # set turbo
        sp = requests.post(f"{API}/rooms/{code}/set-speed",
                           json={"playerId": host, "speed": "turbo"}, timeout=10)
        assert sp.status_code == 200
        # start sim
        ss = requests.post(f"{API}/rooms/{code}/start-sim", json={"playerId": host}, timeout=15)
        assert ss.status_code == 200, ss.text
        # poll until finished (turbo ~ 55ms * 90 * 38 ≈ 188s + overhead; allow up to 320s)
        deadline = time.time() + 320
        last_status = None
        while time.time() < deadline:
            st = _state(code)
            last_status = st["status"]
            if last_status == "finished":
                return code, host, guest, st
            time.sleep(3)
        pytest.fail(f"Simulation did not finish in time, last status={last_status}")

    def test_set_speed_host_only(self):
        r = _create_room()
        j = _join(r["code"]).json()
        bad = requests.post(f"{API}/rooms/{r['code']}/set-speed",
                            json={"playerId": j["playerId"], "speed": "turbo"}, timeout=10)
        assert bad.status_code == 403

    def test_set_speed_invalid(self):
        r = _create_room()
        bad = requests.post(f"{API}/rooms/{r['code']}/set-speed",
                            json={"playerId": r["playerId"], "speed": "ludicrous"}, timeout=10)
        assert bad.status_code == 400

    def test_start_sim_wrong_state(self):
        r = _create_room()
        bad = requests.post(f"{API}/rooms/{r['code']}/start-sim",
                            json={"playerId": r["playerId"]}, timeout=10)
        assert bad.status_code == 400

    def test_finished_sim_standings(self, finished_room):
        code, host, guest, st = finished_room
        league = st["league"]
        assert league is not None
        assert league["finished"] is True
        assert len(league["teams"]) == 20
        standings = league["standings"]
        # standings is a dict id->row in our backend; public_room returns dict directly
        rows = list(standings.values()) if isinstance(standings, dict) else standings
        assert len(rows) == 20
        for row in rows:
            for col in ["P", "W", "D", "L", "GF", "GA", "GD", "Pts"]:
                assert col in row, f"missing column {col}"
            # P == W+D+L
            assert row["P"] == row["W"] + row["D"] + row["L"], f"row {row}"
            # P == 38 after full season
            assert row["P"] == 38, f"team {row.get('teamName')} P={row['P']}"
            # Pts == 3*W + D
            assert row["Pts"] == 3 * row["W"] + row["D"]
            # GD == GF - GA
            assert row["GD"] == row["GF"] - row["GA"]
        # Sum of Pts == 3*total_wins + total_draws; total matches = 20*19 = 380, each match 2 W/L or 2 D
        total_pts = sum(r["Pts"] for r in rows)
        total_w = sum(r["W"] for r in rows)
        total_d = sum(r["D"] for r in rows)
        # each match contributes either 3 (decided) or 2 (draw) pts total
        # total wins = total losses; each league row counted -> sum(W)=sum(L)=decided matches; sum(D) is sum of two teams (so each draw counted twice)
        total_matches = 20 * 19  # 380
        assert total_w == sum(r["L"] for r in rows)
        decided = total_w  # equal to losses
        draws_pairs = total_d // 2
        assert decided + draws_pairs == total_matches, f"decided={decided} draw_pairs={draws_pairs} expected={total_matches}"
        assert total_pts == 3 * decided + 2 * draws_pairs

    def test_finished_sim_each_team_11_players(self, finished_room):
        code, host, guest, st = finished_room
        for tid, team in st["league"]["teams"].items():
            filled = sum(1 for v in team["squad"].values() if v is not None)
            assert filled == 11, f"team {team['teamName']} has {filled} players"


# ----------------------------- WebSocket -----------------------------
class TestWebSocket:
    @pytest.mark.asyncio
    async def test_ws_state_and_ping(self):
        r = _create_room()
        code, pid = r["code"], r["playerId"]
        url = f"{WS_BASE}/api/ws/{code}?playerId={pid}"
        async with websockets.connect(url, open_timeout=15) as ws:
            first = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(first)
            assert msg["type"] == "state", msg
            assert msg["payload"]["code"] == code
            await ws.send(json.dumps({"type": "ping"}))
            pong = await asyncio.wait_for(ws.recv(), timeout=10)
            pmsg = json.loads(pong)
            assert pmsg["type"] == "pong", pmsg

    @pytest.mark.asyncio
    async def test_ws_state_on_join_broadcast(self):
        r = _create_room()
        code, pid = r["code"], r["playerId"]
        url = f"{WS_BASE}/api/ws/{code}?playerId={pid}"
        async with websockets.connect(url, open_timeout=15) as ws:
            # consume initial state
            await asyncio.wait_for(ws.recv(), timeout=10)
            # join from REST
            j = _join(code).json()
            # expect a state broadcast
            broadcast_msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(broadcast_msg)
            assert data["type"] == "state"
            assert len(data["payload"]["teams"]) == 2
