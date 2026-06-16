# 38-0 Brasil - Setup Rápido

## ⚡ Instalação

### Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

### Frontend
```bash
cd frontend
npm install
```

## 🚀 Executar

### Terminal 1 - Backend
```bash
cd backend
source venv/bin/activate
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Backend rodará em: `http://localhost:8000`
WebSocket em: `ws://localhost:8000/api/ws/{code}`

### Terminal 2 - Frontend
```bash
cd frontend
npm start
```

Frontend rodará em: `http://localhost:3000`

## 📱 Fluxo de Uso

### 1. Lobby
- Criar sala (host) ou juntar sala (guest)
- Configurar formação e nome do time
- Host ajusta showOvr se quiser

### 2. Draft
- Host clica "Iniciar Draft"
- Cada jogador drafa 11 players do elenco sorteado
- Ordem snake: vai e volta
- ⚠️ Cada time usa squad_label único (ex: Santos 1962)

### 3. Simulação
- Host clica "Iniciar Temporada"
- 4 Abas: Brasileirão | Copa do Brasil | Libertadores | Sul-Americana
- Host clica "Próxima Rodada" para avançar cada fase
- Gols aparecem ao vivo, tabela atualiza
- Status "Encerrado" quando todas 4 competições terminam

### 4. Resultado Final
- Ver trofeus (campeões de cada comp)
- Ver elencos sem revelar OVR
- Ver classificação final Brasileirão

### 5. Jogar Novamente
- Host clica "Jogar Novamente"
- Mesmos times, novo draft, nova temporada
- Sem criar sala nova

## 🧪 Teste Rápido (1 Player)

Para testar localmente com 1 único jogador:

1. Backend rodando
2. Frontend rodando  
3. Abrir: `http://localhost:3000/`
4. Criar sala
5. Nota: Você é o host, só tem 1 time
   - Draft funciona com 1 time (limitado mas funciona)
   - Simulação começa normalmente
   - Todos os 20 times da liga são NPCs

## 📊 Arquitetura

```
Frontend (React)
├── pages/
│   ├── Home.jsx (criar/juntar sala)
│   ├── Room.jsx (lobby, draft prep)
│   ├── Draft.jsx (draft UI)
│   └── Simulation.jsx (4 abas, live sim)
└── components/
    ├── StandingsTable.jsx
    ├── GroupStandings.jsx
    ├── CupBracket.jsx
    └── SquadDetail.jsx

Backend (FastAPI)
├── server.py (main + endpoints)
├── match_engine.py (sim logic)
├── squads.py (54 elencos brasileiros)
└── requirements.txt

Database: In-memory (Python dicts)
Real-time: WebSocket broadcast
```

## 🐛 Debugging

### Ver console backend
```
INFO: Started server process [12345]
```

### Ver console frontend
```
React DevTools
Network tab > WS para WebSocket
```

### Logs úteis
- Backend: `log.info()` statements
- Frontend: `console.log()` em hooks

## 🔑 Variáveis Ambiente

### Backend (.env)
```
CORS_ORIGINS=http://localhost:3000
```

### Frontend (.env)
```
REACT_APP_BACKEND_URL=http://localhost:8000
```

## ⚙️ Configurações

### Formações (4 opções)
- 4-3-3 (padrão)
- 4-4-2
- 3-5-2
- 4-2-3-1

### Velocidade Simulação
- Lento: 90s por rodada
- Rápido: 20s por rodada (padrão)
- Turbo: 5s por rodada

### Tamanho Ligas
- Brasileirão: 20 times (max 12 humans)
- Copa do Brasil: 16 teams (random draw)
- Libertadores: 8 teams (top 4 + 4 intl)
- Sul-Americana: 8 teams (5-8 + 4 intl)

## 📝 Equipes Históricas Disponíveis

54 elencos de times brasileiros em diferentes épocas:
- Santos (1962, 1963, 1969)
- Flamengo (1981, 2019)
- Palmeiras (1951, 1994)
- Corinthians (1988, 2005, 2017)
- São Paulo (1992, 2005)
- Botafogo (1948, 1962, 1995)
- Cruzeiro (1976, 1997)
- Internacional (1979, 2006)
- E mais... (54 total)

---

**Dúvidas?** Verifique FIXES_APPLIED.md para detalhes técnicos.
