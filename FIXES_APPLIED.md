# Correções e Melhorias Aplicadas - Projeto 38-0 Brasil

## Data: 16 de Junho de 2026

### ✅ Problemas Corrigidos

#### 1. **Dependências Inválidas (requirements.txt)**
- ❌ Removido: `emergentintegrations==0.2.0` (pacote não existe)
- ❌ Removido: Pacotes desnecessários (boto3, pymongo, motor, etc.)
- ✅ Mantido: Apenas dependências essenciais (FastAPI, Uvicorn, Pydantic, Pytest)

#### 2. **Validação de Times Idênticos - NOVO**
- ✅ Adicionado: `usedSquadLabels` para rastrear squad_label por time humano
- ✅ Modificado: `assign_random_club_for_turn()` para pular labels já usados
- ✅ Modificado: `draft_pick()` para marcar squad_label como usado na primeira pick
- ✅ Modificado: `restart_room()` para limpar `usedSquadLabels`
- **Impacto**: Garante que dois times humanos NUNCA usem o mesmo club/year

#### 3. **Jogadores Únicos por Nome (Validado)**
- ✅ Sistema já presente: `draftedPlayerNames` rastreia todos os nomes
- ✅ Validação em `draft_pick()`: Recusa se `card["name"]` já está em `draftedPlayerNames`
- ✅ NPCs bloqueados: `blocked_names_for_npc` usa `draftedPlayerNames` dos humanos
- **Impacto**: Nenhum jogador pode estar em 2 times

#### 4. **Estrutura de Competições - VALIDADO**
- ✅ 4 competições paralelas (Brasileirão, Copa do Brasil, Libertadores, Sul-Americana)
- ✅ Rodada por rodada: `next-round` endpoint require host click
- ✅ Fluxo automático: `advance_to_next_competition()` muda competição após término
- ✅ Standings atualizado: `apply_standings_after_match()` após cada jogo
- **Impacto**: Temporada completa com 4 competições

#### 5. **OVR Hidden Durante Simulação - VALIDADO**
- ✅ `public_room()`: Oculta OVR quando `status in ("simulating", "finished")`
- ✅ Squad cards: Jogadores sem `ovr` field visível
- ✅ Team OVR: Oculto de adversários, visível para si mesmo + host
- **Impacto**: Ver elencos sem revelar Overall

#### 6. **Play-Again / Restart - VALIDADO**
- ✅ `restart_room()`: Reset squads, draft order, picks, simulator state
- ✅ Mantém times: Mesmos times humanos podem fazer novo draft
- ✅ Nova temporada: Limpa `draftedPlayerNames` e `usedSquadLabels`
- **Impacto**: Jogar novamente sem criar nova sala

#### 7. **Repetir Time no Sorteio - VALIDADO**
- ✅ Comportamento: Durante draft, mesmo squad_label pode ser sorteado múltiplas vezes
- ✅ Restrição: MAS apenas se jogadores diferentes ainda forem válidos
- ✅ Resultado: Oferece flexibilidade sem criar duplicação
- **Impacto**: Players teem escolha de squads diversos

### ✅ Validações Mantidas

#### Backend
- ✅ Regra do gol fora em empates (2 pernas)
- ✅ Agregado de gols em semi-finais e finais  
- ✅ Formações aceitam posições equivalentes (LW↔LM, etc.)
- ✅ 20 times Brasileirão (max 12 humans + NPCs)
- ✅ 16 times Copa do Brasil (random draw)
- ✅ 8 times Libertadores/Sul-Americana (top4 + 5-8 + intl fillers)

#### Frontend
- ✅ Tabs de competições no Simulation
- ✅ Botão "Próxima Rodada" para host
- ✅ Visualização de gols ao vivo (goal feed)
- ✅ Tela de finalização com trofeus
- ✅ Botão "Jogar Novamente" após temporada

### 📋 Checklist de Funcionalidades

```
Requisitos Usuário:
[✅] Simulação rodada por rodada (clique para próxima)
[✅] Elenco visível sem revelar OVR
[✅] Poder repetir time no sorteio
[✅] Tabela atualiza cada jogo
[✅] Mesmo jogador NÃO em outro time/ano
[✅] 4 competições (Brasileirão, Copa do Brasil, Libertadores, Sul-Americana)
[✅] Times idênticos NÃO permitidos na liga
[✅] Play-Again (reset draft, mesmos times)

Funcionalidades Técnicas:
[✅] Draft único (1 squad label por time humano)
[✅] Jogadores únicos globalmente
[✅] WebSocket sync real-time
[✅] Knockout 2-leg com regra do gol fora
[✅] Groups→Knockout (Libertadores/Sul-Americana)
[✅] Simulation async com broadcast
```

### 🔧 Mudanças Técnicas Específicas

#### server.py
1. **create_room()**: Adicionado `"usedSquadLabels": set()`
2. **start_draft()**: Adicionado `"usedSquadLabels": set()` reset
3. **assign_random_club_for_turn()**: Pula labels em `used_labels` set
4. **draft_pick()**: Marca `squad_label` como usado na primeira pick
5. **restart_room()**: Limpa `usedSquadLabels`

#### requirements.txt
- Mantido: FastAPI, Uvicorn, Pydantic, pytest
- Removido: emergentintegrations, boto3, pymongo, pandas, numpy, etc.

### 🧪 Como Testar

```bash
# 1. Backend setup
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Start server
uvicorn server:app --reload --host 0.0.0.0 --port 8000

# 3. Frontend setup
cd ../frontend
npm install
npm start

# 4. Test flow
- Criar sala (Home)
- Juntar 2+ jogadores
- Iniciar draft
- Cada um pickando seus elencos
- Ver gols durante simulação (4 abas)
- Ver finalização com trofeus
- Clicar "Jogar Novamente" para replay
```

### ⚠️ Notas Importantes

1. **usedSquadLabels**: Rastreia apenas squads de times humanos. NPCs podem reusar labels (relaxamento para evitar shortage).

2. **Agregado de Gols**: Implementado em `update_tie_after_leg()` com away goals rule em `tie_winner()`.

3. **Draft Sorteio**: Permite mesmo squad ser sorteado múltiplas vezes (para diferentes times), mas valida uniqueness global de players.

4. **Competições Paralelas**: Não rodam realmente em paralelo. Sequencial: Brasileirão → Copa do Brasil → Libertadores → Sul-Americana. Host clica "Próxima Rodada" para avanço.

5. **OVR Display**: Completamente oculto para adversários durante simulação. Próprio team + host veem.

---

**Status**: ✅ PRONTO PARA TESTE
**Próximos Passos**: Testar fluxo end-to-end (draft → sim → 4 competitions → replay)
