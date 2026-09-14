# ⚡ Cripto Bolt — Agente Autônomo de Trading de Criptomoedas

## Visão Geral

O **Cripto Bolt** é um agente autônomo de trading de criptomoedas que opera de forma 100% automatizada seguindo uma estratégia quantitativa baseada em **confluência de 3 fatores**. Ele analisa o mercado, identifica oportunidades, executa trades com gestão de risco rigorosa e reporta resultados — tudo sem intervenção humana.

O sistema foi projetado para operar em **Binance** e **Crypto.com** via API (ccxt), com modo **Paper Trading** ativado por padrão para validação sem risco real.

---

## Arquitetura

```
bot_trader/
├── __init__.py          # Pacote principal
├── db.py                # SQLAlchemy (SQLite cripto_bolt.db)
├── models.py            # TradeIdea + TradeExecucao
├── exchanges.py         # Abstração: Binance, Crypto.com, Paper
├── notificacao.py       # Notificações via Telegram
├── scheduler.py         # APScheduler (6 jobs automáticos)
├── mcp_graficos.py      # MCP Server + gráficos Plotly via IA
└── engines/
    ├── confluencia.py   # Pré-Mercado — Geração de ideias
    ├── abertura.py      # Abertura — Execução de trades
    ├── meio_dia.py      # Meio do Dia — Gestão de risco
    ├── fechamento.py    # Fechamento — P&L diário
    └── semanal.py       # Semanal — Relatório de performance
```

---

## A Estratégia: Confluência de 3 Fatores

O Cripto Bolt utiliza um sistema de **scoring por confluência** para filtrar oportunidades. Cada ativo da watchlist recebe uma pontuação de 0 a 3 baseada em três fatores independentes:

### Fator 1: Técnico (0 ou 1 ponto)

Condições que devem ser **todas verdadeiras** simultaneamente:

| Indicador | Condição |
|-----------|----------|
| **Tendência** | EMA 9 períodos > EMA 21 períodos (tendência de alta) |
| **Momentum** | RSI entre 50 e 70 (força sem sobrecompra) |
| **Rompimento** | Preço atual acima do topo dos últimos 20 períodos |

> **Timeframe**: 1 hora (dados do Yahoo Finance via yfinance)

### Fator 2: Volume (0 ou 1 ponto)

| Indicador | Condição |
|-----------|----------|
| **Volume relativo** | Volume atual > 1.8× média dos últimos 20 períodos |

O volume acima da média confirma que o movimento de preço tem participação real do mercado, reduzindo sinais falsos.

### Fator 3: Sentimento de Mercado (0 ou 1 ponto)

| Indicador | Condição |
|-----------|----------|
| **Análise de IA** | Groq (LLaMA 3.1 70B) classifica sentimento como POSITIVO |

A IA analisa o contexto de mercado atual para o ativo e retorna uma classificação simples: POSITIVO, NEUTRO ou NEGATIVO. Apenas sentimento positivo gera ponto.

### Critério de Aprovação

Uma ideia de trade é **aprovada** quando:

```
Score Total ≥ 2/3  E  R:R (Risco-Retorno) ≥ 2.0
```

---

## Filtro de Regime de Mercado

Antes de analisar qualquer ativo, o Cripto Bolt verifica o **regime macro** do mercado cripto:

```
BTC (preço atual) > EMA 200 (diário) → Mercado FAVORÁVEL → Gerar ideias
BTC (preço atual) < EMA 200 (diário) → Mercado DESFAVORÁVEL → Não operar
```

Se o Bitcoin estiver abaixo da EMA de 200 dias, nenhuma ideia é gerada. Isso protege contra operar em bear markets prolongados.

---

## As 5 Rotinas Diárias

O agente executa automaticamente via APScheduler:

### 1. 🔍 Pré-Mercado (08:30 UTC) — `confluencia.py`

**Objetivo**: Gerar ideias de trade.

1. Verifica regime de mercado (BTC > EMA200)
2. Para cada ativo da watchlist:
   - Calcula score técnico (EMA + RSI + rompimento)
   - Calcula score de volume (1.8× média)
   - Consulta sentimento via Groq
   - Calcula preço de entrada, stop-loss e alvo
3. Aprova ideias com score ≥ 2 e R:R ≥ 2.0
4. Salva no banco de dados e notifica via Telegram

### 2. 📈 Abertura (10:00 UTC) — `abertura.py`

**Objetivo**: Executar trades aprovados.

1. Busca ideias aprovadas e não executadas
2. Valida regras de risco duras:
   - Máximo **6 posições** abertas simultâneas
   - Máximo **3 trades** por semana
   - Máximo **20%** da conta por trade
3. Calcula quantidade: **1% de risco** da conta por trade
4. Envia ordem **Limit Buy** na exchange
5. Cria **Stop-Loss** automático
6. Registra tudo no banco e notifica

### 3. ⚡ Gestão de Risco (12:00 e 15:00 UTC) — `meio_dia.py`

**Objetivo**: Proteger posições abertas.

Aplica regras em cascata para cada posição:

| Regra | Condição | Ação |
|-------|----------|------|
| **Stop Loss** | P&L ≤ -7% | Vende a mercado |
| **Trailing +20%** | P&L ≥ +20% | Sobe stop para garantir +5% |
| **Trailing +15%** | P&L ≥ +15% | Sobe stop para garantir +7% |
| **Tese Violada** | Preço < EMA9 (1h) por >1% | Fecha posição |

> **Regra fundamental**: O stop **nunca é afrouxado** — só pode subir.

### 4. 📊 Fechamento (17:30 UTC) — `fechamento.py`

**Objetivo**: Consolidar resultados do dia.

1. Calcula P&L realizado (trades fechados hoje)
2. Calcula P&L não realizado (posições abertas)
3. Consolida equity total (USDT + posições)
4. Gera relatório detalhado
5. Envia resumo via Telegram

### 5. 📋 Relatório Semanal (Domingo 20:00 UTC) — `semanal.py`

**Objetivo**: Avaliar performance e sugerir ajustes.

Métricas calculadas:
- **Winrate**: % de trades vencedores
- **Profit Factor**: ganhos / perdas
- **Alpha**: performance vs BTC (benchmark)
- **Tipos de saída**: distribuição entre stop, alvo, tese violada

A IA (Groq) analisa os resultados e sugere **3 ajustes** específicos para a próxima semana.

---

## Gestão de Risco

O Cripto Bolt opera com múltiplas camadas de proteção:

### Regras de Entrada (Hard Rules)

| Regra | Limite |
|-------|--------|
| Posições abertas simultâneas | Máximo 6 |
| Trades por semana | Máximo 3 |
| Capital por trade | Máximo 20% da conta |
| Risco por trade | 1% da conta |
| R:R mínimo para aprovação | 2.0:1 |

### Regras de Saída

| Cenário | Ação |
|---------|------|
| Stop-Loss atingido (-7%) | Vende a mercado automaticamente |
| Lucro +15% | Trailing stop garante mínimo +7% |
| Lucro +20% | Trailing stop garante mínimo +5% |
| EMA9 perdida em lucro | Fecha posição (tese violada) |

### Proteção Macro

| Condição | Ação |
|----------|------|
| BTC abaixo da EMA200 | Não gera novas ideias |
| Score < 2/3 | Ideia rejeitada |
| R:R < 2.0 | Ideia rejeitada |

---

## Setup do Trade

Quando uma ideia é aprovada, os preços são calculados automaticamente:

```
Entrada = Preço atual de fechamento
Stop    = Fundo dos últimos 10 períodos × 0.99 (1% margem)
Alvo    = Entrada + (Risco × 2.5)
```

Exemplo:
```
BTC/USDT
  Entrada: $67,500.00
  Stop:    $64,800.00  (fundo 10 períodos × 0.99)
  Risco:   $2,700.00
  Alvo:    $74,250.00  (entrada + risco × 2.5)
  R:R:     2.5:1
```

---

## Exchanges Suportadas

| Exchange | Implementação | Stop-Loss |
|----------|--------------|-----------|
| **Binance** | ccxt.binance | STOP_LOSS_LIMIT (limit = stop × 0.998) |
| **Crypto.com** | ccxt.cryptocom | Stop nativo |
| **Paper Trading** | Simulação local | Em memória (preços reais da Binance) |

O Paper Trading usa **$10.000 USDT** de saldo inicial e preços reais da Binance para simular operações sem risco.

---

## Watchlist Padrão

| Par | Ativo |
|-----|-------|
| BTC/USDT | Bitcoin |
| ETH/USDT | Ethereum |
| SOL/USDT | Solana |
| BNB/USDT | Binance Coin |
| ADA/USDT | Cardano |
| XRP/USDT | Ripple |

Configurável via `.env` (`BOT_TRADER_WATCHLIST`).

---

## Notificações

O Cripto Bolt envia notificações em tempo real via **Telegram Bot API**:

| Evento | Conteúdo |
|--------|----------|
| Pré-Mercado | Ideias aprovadas com scores e setup |
| Abertura | Trades executados com qty, entrada, stop, alvo |
| Gestão de Risco | Stops ajustados ou posições fechadas |
| Fechamento | P&L do dia + equity total |
| Semanal | Performance completa + sugestões da IA |

---

## Gráficos Inteligentes (MCP)

O módulo MCP permite gerar gráficos via IA:

- **Equity Curve**: Evolução do capital ao longo do tempo
- **P&L por Ativo**: Barras de lucro/prejuízo por criptomoeda
- **Winrate**: Gráfico de pizza (winners vs losers)
- **Gráfico Customizado**: Descreva em linguagem natural e a IA gera o código Plotly

---

## Dashboard (Streamlit)

Acessível em **⚡ Cripto Bolt** no painel admin:

### KPIs em Tempo Real
- Total de Trades | Posições Abertas | P&L Total | Winrate | Profit Factor

### Gráficos Interativos
- Curva de Equity (Plotly)
- P&L por Ativo (barras coloridas)

### Tabs
- **Posições Abertas**: Detalhes de cada posição ativa
- **Ideias Recentes**: Últimas 20 ideias com scores e status
- **Histórico**: Trades fechados com P&L detalhado
- **Scheduler**: Controle e execução manual das rotinas

---

## Tecnologias Utilizadas

| Tecnologia | Uso |
|------------|-----|
| **Python** | Linguagem principal |
| **SQLAlchemy + SQLite** | Persistência de trades e ideias |
| **ccxt** | API unificada para exchanges |
| **yfinance** | Dados de mercado (OHLCV) |
| **ta** | Indicadores técnicos (EMA, RSI) |
| **Groq (LLaMA 3.1 70B)** | Análise de sentimento + sugestões |
| **APScheduler** | Agendamento das 5 rotinas |
| **Plotly** | Gráficos interativos |
| **FastMCP** | Server MCP para charts via IA |
| **Streamlit** | Dashboard web |
| **Telegram Bot API** | Notificações em tempo real |

---

## Configuração

### Variáveis de Ambiente (.env)

```env
# Modo de operação
BOT_TRADER_PAPER_MODE=true        # true = simulação, false = dinheiro real
BOT_TRADER_EXCHANGE=binance       # binance ou cryptocom
BOT_TRADER_WATCHLIST=BTC/USDT,ETH/USDT,SOL/USDT

# Exchange (necessário para modo real)
BINANCE_API_KEY=sua_chave
BINANCE_API_SECRET=seu_secret

# Notificações
TELEGRAM_BOT_TOKEN=seu_token
TELEGRAM_CHAT_ID=seu_chat_id

# IA (já existente)
GROQ_API_KEY=sua_chave_groq
```

### Inicialização

O scheduler é iniciado automaticamente pelo dashboard ou pode ser controlado manualmente:

```python
from bot_trader.scheduler import iniciar_scheduler, parar_scheduler

iniciar_scheduler()   # Inicia os 6 jobs automáticos
parar_scheduler()     # Para o scheduler
```

---

## Fluxo Completo de um Dia

```
08:30 ─── PRÉ-MERCADO ──────────────────────────────────────────
         │ 1. Verifica: BTC > EMA200? ✅
         │ 2. Analisa watchlist (6 ativos)
         │ 3. BTC/USDT: Score 3/3 (Técnico ✅ Volume ✅ News ✅)
         │    R:R = 2.5 → APROVADA ✅
         │ 4. ETH/USDT: Score 1/3 → REJEITADA ❌
         │ 5. Notifica Telegram
         │
10:00 ─── ABERTURA ──────────────────────────────────────────────
         │ 1. Busca ideias aprovadas: BTC/USDT
         │ 2. Valida: 2/6 posições, 1/3 semanal → OK
         │ 3. Calcula: 1% risco → 0.015 BTC
         │ 4. Envia: Limit Buy 0.015 BTC @ $67,500
         │ 5. Cria: Stop-Loss @ $64,800
         │ 6. Notifica Telegram
         │
12:00 ─── GESTÃO DE RISCO ──────────────────────────────────────
         │ 1. BTC/USDT: +3.2% → Nenhuma ação
         │ 2. SOL/USDT: -7.5% → STOP ATIVADO → Vende a mercado
         │ 3. Notifica Telegram
         │
15:00 ─── GESTÃO DE RISCO ──────────────────────────────────────
         │ 1. BTC/USDT: +16.1% → Trailing: Stop sobe para +7%
         │ 2. Notifica Telegram
         │
17:30 ─── FECHAMENTO ───────────────────────────────────────────
         │ P&L Realizado:     -$68.50 (SOL stop)
         │ P&L Não Realizado: +$157.30 (BTC aberto)
         │ P&L Total:         +$88.80
         │ Equity:            $10,088.80
         │ Notifica Telegram
         │
Domingo 20:00 ─── RELATÓRIO SEMANAL ────────────────────────────
         │ Total Trades: 5
         │ Winrate: 60% (3W / 2L)
         │ Profit Factor: 2.3
         │ P&L Semanal: +$312.50
         │ BTC Semanal: +4.2%
         │ Alpha: +$145.00
         │
         │ Sugestões da IA:
         │ 1. Aumentar filtro de volume para 2.0× nos altcoins
         │ 2. Considerar trailing mais agressivo em +25%
         │ 3. Winrate sólido, manter critérios atuais
```

---

## Segurança

- **Paper Trading por padrão**: Nenhuma operação real sem configuração explícita
- **Chaves de API separadas**: Binance e Crypto.com isolados
- **Stop-Loss automático**: Toda posição nasce com proteção
- **Limites de exposição**: Máximo 6 posições, 20% por trade, 1% risco
- **Regime de mercado**: Não opera em bear market (BTC < EMA200)
- **Logs detalhados**: Todas as ações são registradas

---

## Licença

Uso interno — Oráculo Empresarial.

---

*Cripto Bolt v1.0.0 — Agente Autônomo de Trading*
