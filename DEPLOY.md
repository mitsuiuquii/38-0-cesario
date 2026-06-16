# 🚀 Deploy 38-0 Brasil | Vercel + Render

## 📋 Resumo
- **Frontend**: Vercel (React, hospedagem estática)
- **Backend**: Render (Python FastAPI, hospedagem serverless)
- **Tempo**: ~15-20 minutos

---

## PASSO 1️⃣: Preparar Repositório GitHub

```bash
# Se ainda não tem um repo GitHub
cd /home/mitsuiuquimurillo/380cesario/38-0-cesario
git init
git add .
git commit -m "Initial commit - 38-0 Brasil"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/38-0-cesario.git
git push -u origin main
```

---

## PASSO 2️⃣: Deploy Backend no Render

### 2.1 Criar Conta Render
1. Ir para https://render.com
2. Clique em **Sign Up** (pode usar GitHub direto)
3. Conecte seu repositório GitHub

### 2.2 Deploy Backend
1. Dashboard → **New +** → **Web Service**
2. Conecte seu repositório `38-0-cesario`
3. **Runtime**: Python 3.11
4. **Build Command**:
   ```
   pip install -r requirements.txt
   ```
5. **Start Command**:
   ```
   cd backend && uvicorn server:app --host 0.0.0.0 --port $PORT
   ```
6. **Environment Variables** (clique em **Add Environment Variable**):
   ```
   PYTHONUNBUFFERED: true
   CORS_ORIGINS: https://seu-frontend-vercel-url.vercel.app
   ```
   *(Atualizar a URL do Vercel após deploy do frontend)*

7. **Plan**: Free (recomendado)
8. Clique **Create Web Service**

**Salve a URL do backend que aparecerá**: `https://38-0-cesario.onrender.com`

---

## PASSO 3️⃣: Deploy Frontend no Vercel

### 3.1 Instalar Vercel CLI
```bash
npm install -g vercel
```

### 3.2 Login Vercel
```bash
vercel login
# Escolha GitHub e autorize
```

### 3.3 Deploy Frontend
```bash
cd /path/to/frontend
vercel --prod
```

Durante o deploy, o Vercel vai perguntar:
- **Project name**: `38-0-cesario`
- **Framework**: React ✓
- **Build command**: `npm run build` ✓
- **Output directory**: `build` ✓

**Salve a URL do frontend**: `https://38-0-cesario.vercel.app`

---

## PASSO 4️⃣: Conectar Frontend ao Backend

### 4.1 Criar `.env.local` no Frontend (Vercel)
```bash
cd frontend
echo "REACT_APP_BACKEND_URL=https://38-0-cesario.onrender.com" > .env.local
```

### 4.2 Deploy Frontend Novamente
```bash
vercel --prod
```

---

## PASSO 5️⃣: Atualizar CORS no Backend

### 5.1 Voltar ao Render Dashboard
1. Selecione **38-0-cesario** web service
2. Vá em **Environment**
3. Edite a variável `CORS_ORIGINS`:
   ```
   CORS_ORIGINS: https://38-0-cesario.vercel.app
   ```
4. Salve (o backend vai fazer redeploy automaticamente)

---

## ✅ Verificar Deploy

### 1. Testar Frontend
```bash
curl https://seu-frontend.vercel.app
# Deve retornar HTML
```

### 2. Testar Backend
```bash
curl https://seu-backend.onrender.com/health
# Deve retornar JSON com status
```

### 3. Jogar!
Abra no navegador: `https://seu-frontend.vercel.app`

---

## 🔗 Compartilhar com Amigos
Envie apenas o link do frontend:
```
https://seu-frontend.vercel.app
```

Seus amigos podem:
1. Criar uma sala
2. Compartilhar o código da sala com você
3. Você junta a sala
4. Começam o draft!

---

## 🐛 Troubleshooting

### "CORS Error" no console
**Solução**: Verificar se `CORS_ORIGINS` no Render contém exatamente a URL do Vercel

### "Backend não responde"
**Solução**: 
- Checar se Render web service está running (pode levar 1-2 min para iniciar)
- Visite `https://seu-backend.onrender.com/health` para testar

### "Vercel build falha"
**Solução**: 
- Verificar logs: `vercel logs`
- Garantir que `npm run build` funciona localmente

### "WebSocket connection refused"
**Solução**:
- Render suporta WebSocket ✓
- Verificar se `ws://` está sendo convertido para `wss://` automaticamente
- Se não, adicionar ao server.py:
```python
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],
)
```

---

## 📊 Arquivos Adicionados para Deploy

- ✅ `vercel.json` - Configuração Vercel
- ✅ `render.yaml` - Configuração Render  
- ✅ `.env.example` - Template de variáveis

---

## 💰 Custo Estimado

- **Vercel**: GRÁTIS (até 100GB/mês)
- **Render**: GRÁTIS (com limite de 750 horas/mês)
- **Total**: R$ 0

---

## 🎮 Próximas Sessões

Após deploy, você pode:
1. ✅ Criar sala com amigos
2. ✅ Todos fazem draft
3. ✅ Simular temporada multiplayer
4. ✅ Compartilhar score final

---

**Dúvidas?** Verifique os logs:
- **Vercel**: `vercel logs`
- **Render**: Dashboard → Web Service → Logs

