# 38-0 Brasil — PRD

## Original Problem Statement
Multiplayer Brazilian football draft & league simulation web app. Friends join a shared room and snake-draft historical players from real Brazilian club squads (Pelé era → present) into 11-man teams, then watch a 38-round Brasileirão simulate in real time across all browsers. Tech: React + Tailwind + FastAPI + MongoDB + WebSockets. Portuguese (BR).

## Architecture
- **Backend**: FastAPI + WebSockets, in-memory `ROOMS` dict for live game state. MongoDB available but unused for ephemeral game sessions.
- **Realtime**: Each room has a WebSocket channel (`/api/ws/{code}`) that broadcasts `state`, `pick`, `round_start`, `tick`, `round_end`, `sim_complete` events to all participants.
- **Match engine** (`match_engine.py`): Poisson-based goal generation, ±5 OVR random per-round form modifier, +2.5 home advantage; double round-robin fixture generator yielding 38 rounds for 20 teams (humans + NPC fill).
- **Frontend**: React Router with 4 screens (Home, Room, Draft, Simulation) + Sonner toasts.

## User Persona
Groups of friends (2–12 people) who want a quick, hype, real-time football draft game inspired by FIFA Ultimate Team + Football Manager. No login required; just a name + team name.

## Core Requirements (static)
1. Snake-draft from a pool of 28 historical Brazilian squads / 392 real players with era-coherent OVRs (Pelé/Romário/Zico/Ronaldinho 93–99; club legends 80–92; regulars 65–79; subs 55–64).
2. Formations 4-3-3, 4-4-2, 3-5-2, 4-2-3-1 selectable per player; pitch visualizer reflects formation in real time.
3. Strict position rules with sensible wide/midfield flexibility.
4. 38-round Brasileirão simulation with animated 1–90 minute clock, goal events, flavour events, configurable speed (slow/fast/turbo).
5. Standings with color zones (Libertadores green / Sul-Americana blue / Relegation red), own-team highlighted.

## What's Been Implemented (2026-02)
- Backend REST endpoints + WebSocket realtime sync (all 13 endpoints).
- 28 historical squads, 392 era-accurate players (`squads.py`).
- Match engine with Poisson goals, scorer weighting by position.
- Snake draft with random club assignment per turn (only clubs that have at least one valid open-slot player).
- NPC team auto-fill so league always reaches 20 teams.
- Home / Room (lobby with formation picker, star button, host OVR toggle) / Draft (pitch + available player cards + side-panel turn tracker) / Simulation (animated clocks, goal feed, live standings, host speed selector) / Final champion screen.
- 23/23 backend tests passing; UI tested for create→room→draft flows.

## Backlog (P0 / P1 / P2)
- **P1**: Add backoff to WebSocket reconnect; explicit error-state data-testids; final results screen with top scorers/MVP and shareable link.
- **P1**: Persist room results in MongoDB so players can revisit the table after disconnect.
- **P2**: Subdivide `server.py` (currently ~680 lines) into routers + sim_loop module.
- **P2**: Sound effects (goal horn, whistle).
- **P2**: Spectator-only invite link.
- **P2**: Add 5 more squads (Santos 2011 Neymar, Flamengo 1992 Bebeto, Cruzeiro 1966 Tostão, Atlético-PR 2004, Inter 2010).

## Next Tasks
1. Wait for user feedback on initial build.
2. Address any flow issues raised during play-testing.
3. Add P1 enhancements (persistence + final results detail).
