"""
╔══════════════════════════════════════════════════════════════════╗
║       CRIPTO BOLT — Módulo de Inteligência com Perplexity AI    ║
║       Powered by Sonar Pro + Search API                          ║
║                                                                  ║
║  Versão  : 1.0.0                                                 ║
║  Base URL: https://api.perplexity.ai                             ║
║  Modelo  : sonar-pro (pesquisa web em tempo real + citações)     ║
╚══════════════════════════════════════════════════════════════════╝

Funcionalidades:
  - Análise de sentimento de mercado via web em tempo real
  - Pesquisa de notícias e eventos relevantes para um ativo
  - Análise fundamentalista de tokens (projeto, equipe, roadmap)
  - Verificação de segurança de contratos (rug pull, exploits)
  - Resumo de tendências DeFi e pools de liquidez
  - Análise de narrativa (hype, FUD, ciclo de mercado)
  - Geração de relatório completo pré-operação
  - Sistema de score de confiança (0–100) para tomada de decisão
"""

from __future__ import annotations
import logging
import time
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import requests
from settings import get_setting

logger = logging.getLogger(__name__)

# ─── Enums ────────────────────────────────────────────────────────


class SentimentoMercado(str, Enum):
    MUITO_BULLISH = "MUITO_BULLISH"
    BULLISH = "BULLISH"
    NEUTRO = "NEUTRO"
    BEARISH = "BEARISH"
    MUITO_BEARISH = "MUITO_BEARISH"
    INDEFINIDO = "INDEFINIDO"


class NivelRisco(str, Enum):
    MUITO_BAIXO = "MUITO_BAIXO"
    BAIXO = "BAIXO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"
    CRITICO = "CRITICO"

# ─── Exceções ─────────────────────────────────────────────────────


class PerplexityConfigError(Exception):
    """Chave de API ausente ou inválida."""


class PerplexityRequestError(Exception):
    """Falha na requisição à API da Perplexity."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.status_code = status_code
        super().__init__(
            f"{message}" + (f" | http={status_code}" if status_code else "")
        )

# ─── Dataclasses ──────────────────────────────────────────────────


@dataclass
class AnalisePerplexity:
    """Resultado estruturado de qualquer análise via Perplexity."""
    query:         str
    resposta:      str
    citacoes:      List[str] = field(default_factory=list)
    modelo:        str = "sonar-pro"
    tokens_usados: int = 0
    raw:           Dict[str, Any] = field(default_factory=dict)


@dataclass
class RelatorioPreOperacao:
    """
    Relatório completo gerado antes de uma operação de trading.
    Score de 0 a 100 — quanto maior, mais seguro operar.
    """
    symbol:          str
    sentimento:      SentimentoMercado
    nivel_risco:     NivelRisco
    score_confianca: int                 # 0–100
    recomendacao:    str                 # OPERAR / AGUARDAR / NÃO OPERAR
    noticias:        AnalisePerplexity = None
    fundamentals:    AnalisePerplexity = None
    seguranca:       AnalisePerplexity = None
    narrativa:       AnalisePerplexity = None
    contexto_mercado: Dict[str, Any] = field(default_factory=dict)
    fatores_score:   Dict[str, Any] = field(default_factory=dict)
    resumo_final:    str = ""
    timestamp:       float = field(default_factory=time.time)

# ─── Cliente Principal ────────────────────────────────────────────


class PerplexityAnalyst:
    """
    Integra a Perplexity AI ao Cripto Bolt para análise inteligente
    de mercado com pesquisa web em tempo real (Sonar Pro).

    Variável de ambiente:
        PERPLEXITY_API_KEY — perplexity.ai/settings → aba '</> API'

    Modelos disponíveis:
        sonar               — rápido, pesquisa básica
        sonar-pro           — pesquisa profunda + citações ✅ recomendado
        sonar-reasoning     — raciocínio passo a passo
        sonar-reasoning-pro — raciocínio avançado + pesquisa web
    """

    BASE_URL = "https://api.perplexity.ai"

    SYSTEM_PROMPT = (
        "Você é um analista especialista em mercado de criptomoedas, DeFi, "
        "tokens, pools de liquidez e trading. Sua missão é fornecer análises "
        "precisas, objetivas e baseadas em dados reais e atuais da web. "
        "Sempre cite fontes confiáveis. Seja direto e estruturado nas respostas. "
        "Use linguagem técnica mas acessível. Quando houver incerteza, indique "
        "claramente o nível de confiança da informação."
    )

    _SENTIMENTO_MAP = {
        SentimentoMercado.MUITO_BULLISH: 18,
        SentimentoMercado.BULLISH: 10,
        SentimentoMercado.NEUTRO: 0,
        SentimentoMercado.BEARISH: -10,
        SentimentoMercado.MUITO_BEARISH: -18,
        SentimentoMercado.INDEFINIDO: -4,
    }

    _RISCO_MAP = {
        NivelRisco.MUITO_BAIXO: 14,
        NivelRisco.BAIXO: 8,
        NivelRisco.MEDIO: 0,
        NivelRisco.ALTO: -16,
        NivelRisco.CRITICO: -28,
    }

    def __init__(self, modelo: str = "sonar-pro") -> None:
        self.api_key = (get_setting(
            "PERPLEXITY_API_KEY", default="") or "").strip()
        self.modelo = modelo
        self.timeout = int(get_setting("REQUEST_TIMEOUT", default="30"))
        self.max_retries = int(get_setting("PERPLEXITY_MAX_RETRIES", default="2"))

        if not self.api_key:
            raise PerplexityConfigError(
                "PERPLEXITY_API_KEY não configurada. "
                "Acesse perplexity.ai/settings → aba API → 'Generate API Key' "
                "e adicione ao .env como PERPLEXITY_API_KEY."
            )

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        })

    # ── Método Base ──────────────────────────────────────────────

    def _pesquisar(
        self,
        query: str,
        system_extra: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.2,
        search_recency_filter: str = "day",
    ) -> AnalisePerplexity:
        """
        Envia query à Perplexity Sonar Pro com pesquisa web em tempo real.

        Args:
            query                 : Pergunta ou instrução de análise
            system_extra          : Contexto adicional ao system prompt
            max_tokens            : Limite de tokens na resposta
            temperature           : 0.0=determinístico / 1.0=criativo
            search_recency_filter : hour | day | week | month
        """
        system = self.SYSTEM_PROMPT
        if system_extra:
            system += f"\n\nContexto adicional: {system_extra}"

        payload = {
            "model":   self.modelo,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": query},
            ],
            "max_tokens":               max_tokens,
            "temperature":              temperature,
            "search_recency_filter":    search_recency_filter,
            "return_citations":         True,
            "return_related_questions": False,
        }

        last_error = None
        for tentativa in range(1, self.max_retries + 2):
            try:
                resp = self._session.post(
                    f"{self.BASE_URL}/chat/completions",
                    json=payload,
                    timeout=self.timeout,
                )
                break
            except requests.RequestException as exc:
                last_error = exc
                if tentativa > self.max_retries:
                    raise PerplexityRequestError(f"Falha de conexão: {exc}") from exc
                logger.warning(
                    "Perplexity timeout/rede | tentativa=%d/%d | query=%.80s... | erro=%s",
                    tentativa,
                    self.max_retries + 1,
                    query,
                    exc,
                )
                time.sleep(min(2 * tentativa, 4))

        if last_error and 'resp' not in locals():
            raise PerplexityRequestError(f"Falha de conexão: {last_error}") from last_error

        if not resp.ok:
            raise PerplexityRequestError(
                f"Erro na API Perplexity: {resp.text[:300]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        resposta = data["choices"][0]["message"]["content"]
        citacoes = data.get("citations", [])
        tokens = data.get("usage", {}).get("total_tokens", 0)

        logger.info("🔍 Perplexity | modelo=%s | tokens=%d | query=%.80s...",
                    self.modelo, tokens, query)

        return AnalisePerplexity(
            query=query, resposta=resposta, citacoes=citacoes,
            modelo=self.modelo, tokens_usados=tokens, raw=data,
        )

    def _pesquisar_com_fallback(
        self,
        query: str,
        *,
        fallback_resposta: str,
        system_extra: str = "",
        max_tokens: int = 1024,
        temperature: float = 0.2,
        search_recency_filter: str = "day",
    ) -> AnalisePerplexity:
        try:
            return self._pesquisar(
                query=query,
                system_extra=system_extra,
                max_tokens=max_tokens,
                temperature=temperature,
                search_recency_filter=search_recency_filter,
            )
        except PerplexityRequestError as exc:
            logger.warning("Fallback Perplexity acionado | query=%.80s... | erro=%s", query, exc)
            return AnalisePerplexity(
                query=query,
                resposta=fallback_resposta,
                citacoes=[],
                modelo=f"{self.modelo}-fallback",
                tokens_usados=0,
                raw={"fallback": True, "error": str(exc)},
            )

    def _extrair_sentimento(self, texto: str) -> SentimentoMercado:
        texto_up = (texto or "").upper()
        for sentimento in (
            SentimentoMercado.MUITO_BULLISH,
            SentimentoMercado.BULLISH,
            SentimentoMercado.NEUTRO,
            SentimentoMercado.BEARISH,
            SentimentoMercado.MUITO_BEARISH,
        ):
            if sentimento.value in texto_up:
                return sentimento
        return SentimentoMercado.INDEFINIDO

    def _extrair_risco(self, texto: str) -> NivelRisco:
        texto_up = (texto or "").upper()
        for risco in (
            NivelRisco.CRITICO,
            NivelRisco.ALTO,
            NivelRisco.MEDIO,
            NivelRisco.BAIXO,
            NivelRisco.MUITO_BAIXO,
        ):
            if risco.value in texto_up:
                return risco
        return NivelRisco.MEDIO

    def _extrair_nota_fundamentals(self, texto: str) -> Optional[float]:
        match = re.search(r'(?:nota|score|potencial)\D{0,12}(\d{1,2})(?:[.,](\d))?\s*(?:/\s*10)?', texto, re.IGNORECASE)
        if not match:
            match = re.search(r'\b(10|[1-9])(?:[.,](\d))?\s*/\s*10\b', texto)
        if not match:
            return None
        inteiro = match.group(1)
        decimal = match.group(2) or "0"
        return float(f"{inteiro}.{decimal}")

    def _formatar_contexto_mercado(self, contexto_mercado: Optional[Dict[str, Any]]) -> str:
        if not contexto_mercado:
            return ""
        linhas = []
        for chave, valor in contexto_mercado.items():
            if valor in (None, "", [], {}):
                continue
            rotulo = chave.replace("_", " ").upper()
            linhas.append(f"- {rotulo}: {valor}")
        if not linhas:
            return ""
        return "\nCONTEXTO QUANTITATIVO DO PROJETO:\n" + "\n".join(linhas)

    def _pontuar_contexto_mercado(self, contexto_mercado: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not contexto_mercado:
            return {
                "contexto": 0,
                "momentum": 0,
                "liquidez": 0,
                "estrutura_defi": 0,
                "execucao": 0,
                "bloqueios": [],
            }

        fatores = {
            "contexto": 0,
            "momentum": 0,
            "liquidez": 0,
            "estrutura_defi": 0,
            "execucao": 0,
            "bloqueios": [],
        }

        change_24h = float(contexto_mercado.get("percent_change_24h", 0) or 0)
        change_7d = float(contexto_mercado.get("percent_change_7d", 0) or 0)
        vol_mcap_ratio = float(contexto_mercado.get("volume_market_cap_ratio", 0) or 0)
        tvl_change_7d = float(contexto_mercado.get("tvl_change_7d", 0) or 0)
        tvl_change_1d = float(contexto_mercado.get("tvl_change_1d", 0) or 0)
        pool_score = float(contexto_mercado.get("pool_score", 0) or 0)
        il_7d = float(contexto_mercado.get("il_7d", 0) or 0)
        funding_rate = float(contexto_mercado.get("funding_rate", 0) or 0)
        spread_bps = float(contexto_mercado.get("bid_ask_spread_bps", 0) or 0)
        order_book_imbalance = float(contexto_mercado.get("order_book_imbalance_ratio", 0) or 0)
        open_interest_usd = float(contexto_mercado.get("open_interest_usd", 0) or 0)

        momentum = 0
        if change_24h > 0:
            momentum += min(6, round(change_24h / 2))
        else:
            momentum += max(-6, round(change_24h / 2))
        if change_7d > 0:
            momentum += min(8, round(change_7d / 3))
        else:
            momentum += max(-8, round(change_7d / 3))
        fatores["momentum"] = int(momentum)

        liquidez = 0
        if vol_mcap_ratio >= 0.12:
            liquidez += 8
        elif vol_mcap_ratio >= 0.05:
            liquidez += 4
        elif vol_mcap_ratio > 0:
            liquidez -= 3
        if context := contexto_mercado.get("market_cap"):
            if float(context) < 20_000_000:
                liquidez -= 5
                fatores["bloqueios"].append("market_cap_baixo")
        fatores["liquidez"] = int(liquidez)

        estrutura_defi = 0
        if tvl_change_7d:
            estrutura_defi += 6 if tvl_change_7d > 5 else (-6 if tvl_change_7d < -5 else 0)
        if tvl_change_1d:
            estrutura_defi += 3 if tvl_change_1d > 2 else (-3 if tvl_change_1d < -2 else 0)
        if pool_score:
            estrutura_defi += 8 if pool_score >= 60 else (3 if pool_score >= 40 else -6)
        if il_7d <= -8:
            estrutura_defi -= 6
            fatores["bloqueios"].append("il_elevado")
        fatores["estrutura_defi"] = int(estrutura_defi)

        execucao = 0
        if open_interest_usd >= 500_000_000:
            execucao += 6
        elif open_interest_usd >= 100_000_000:
            execucao += 3
        elif open_interest_usd > 0:
            execucao -= 2
        if 0 < spread_bps <= 3:
            execucao += 4
        elif spread_bps > 12:
            execucao -= 5
            fatores["bloqueios"].append("spread_alto")
        if order_book_imbalance >= 1.15:
            execucao += 3
        elif 0 < order_book_imbalance <= 0.85:
            execucao -= 3
        if funding_rate >= 0.0008:
            execucao -= 4
        elif funding_rate <= -0.0005:
            execucao += 2
        fatores["execucao"] = int(execucao)

        fatores["contexto"] = fatores["momentum"] + fatores["liquidez"] + fatores["estrutura_defi"] + fatores["execucao"]
        return fatores

    def _calcular_score_deterministico(
        self,
        sentimento: SentimentoMercado,
        risco: NivelRisco,
        fundamentals_score: Optional[float],
        contexto_mercado: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        fatores_contexto = self._pontuar_contexto_mercado(contexto_mercado)
        fatores = {
            "base": 50,
            "sentimento": self._SENTIMENTO_MAP.get(sentimento, 0),
            "risco": self._RISCO_MAP.get(risco, 0),
            "fundamentals": 0,
            "contexto": fatores_contexto["contexto"],
            "momentum": fatores_contexto["momentum"],
            "liquidez": fatores_contexto["liquidez"],
            "estrutura_defi": fatores_contexto["estrutura_defi"],
            "execucao": fatores_contexto["execucao"],
            "bloqueios": fatores_contexto["bloqueios"],
        }
        if fundamentals_score is not None:
            fatores["fundamentals"] = max(-12, min(12, round((fundamentals_score - 5) * 2.4)))

        bruto = (
            fatores["base"]
            + fatores["sentimento"]
            + fatores["risco"]
            + fatores["fundamentals"]
            + fatores["contexto"]
        )
        score = max(0, min(100, int(round(bruto))))

        if risco == NivelRisco.CRITICO:
            recomendacao = "NÃO OPERAR"
        elif risco == NivelRisco.ALTO or "market_cap_baixo" in fatores["bloqueios"] or "spread_alto" in fatores["bloqueios"]:
            recomendacao = "AGUARDAR" if score >= 45 else "NÃO OPERAR"
        elif score >= 72:
            recomendacao = "OPERAR"
        elif score >= 52:
            recomendacao = "AGUARDAR"
        else:
            recomendacao = "NÃO OPERAR"

        fatores["score_bruto"] = bruto
        fatores["score_final"] = score
        fatores["recomendacao"] = recomendacao
        return fatores

    # ══════════════════════════════════════════════════════════════
    # BLOCO 1 — Análises Especializadas de Mercado
    # ══════════════════════════════════════════════════════════════

    def analisar_noticias(
        self, symbol: str, nome_completo: str = ""
    ) -> AnalisePerplexity:
        """Busca notícias das últimas 24h. Classifica cada uma como
        POSITIVA, NEGATIVA ou NEUTRA. Destaca hacks, exploits e listings."""
        nome = nome_completo or symbol
        query = (
            f"Quais são as principais notícias sobre {nome} ({symbol}) "
            f"nas últimas 24 horas? Classifique cada notícia como POSITIVA, "
            f"NEGATIVA ou NEUTRA para o preço. Destaque qualquer evento crítico "
            f"como hack, exploit, regulatory action ou listing em exchange."
        )
        return self._pesquisar(query, search_recency_filter="day", max_tokens=800)

    def analisar_sentimento(self, symbol: str) -> AnalisePerplexity:
        """Analisa sentimento via Twitter/X, Reddit e Telegram.
        Retorna: MUITO_BULLISH | BULLISH | NEUTRO | BEARISH | MUITO_BEARISH."""
        query = (
            f"Analise o sentimento atual do mercado para {symbol} com base em "
            f"Twitter/X, Reddit, Telegram e mídia especializada em cripto. "
            f"Classifique como: MUITO_BULLISH, BULLISH, NEUTRO, BEARISH ou "
            f"MUITO_BEARISH. Justifique com evidências concretas."
        )
        return self._pesquisar(query, search_recency_filter="day", max_tokens=600)

    def analisar_fundamentals(
        self, symbol: str, nome_completo: str = ""
    ) -> AnalisePerplexity:
        """Análise fundamentalista: utilidade, equipe, tokenomics,
        parcerias e roadmap. Retorna nota de 1 a 10."""
        nome = nome_completo or symbol
        query = (
            f"Faça uma análise fundamentalista de {nome} ({symbol}): "
            f"1) Qual é a utilidade real do token? "
            f"2) A equipe é doxxed e tem credibilidade? "
            f"3) Qual o tokenomics (supply, distribuição, vesting)? "
            f"4) Existem parcerias e integrações reais? "
            f"5) Qual o estágio atual do roadmap? "
            f"Dê uma nota de 1 a 10 para o potencial fundamentalista."
        )
        return self._pesquisar(
            query, search_recency_filter="week",
            max_tokens=1000, temperature=0.1,
        )

    def verificar_seguranca(
        self, symbol: str, contrato: str = ""
    ) -> AnalisePerplexity:
        """Verifica riscos: rug pull, exploits, auditorias e blacklists.
        Classifica risco como MUITO_BAIXO | BAIXO | MEDIO | ALTO | CRITICO."""
        extra = f" (endereço: {contrato})" if contrato else ""
        query = (
            f"Verifique os riscos de segurança de {symbol}{extra}: "
            f"1) Existe algum histórico de exploit ou hack? "
            f"2) O contrato foi auditado? Por qual empresa? "
            f"3) Existem red flags de rug pull (concentração de tokens, "
            f"sem lock de liquidez)? "
            f"4) O projeto está em alguma blacklist de scam? "
            f"Classifique o risco: MUITO_BAIXO, BAIXO, MEDIO, ALTO ou CRITICO."
        )
        return self._pesquisar(
            query, search_recency_filter="week",
            max_tokens=800, temperature=0.1,
        )

    def analisar_narrativa(self, symbol: str) -> AnalisePerplexity:
        """Analisa ciclo de hype, narrativa dominante (AI/DeFi/RWA/L2),
        acumulação de whales e momentum atual."""
        query = (
            f"Qual é a narrativa atual de mercado para {symbol}? "
            f"1) Em qual fase do ciclo de hype o projeto está? "
            f"2) Qual é a narrativa dominante (AI, DeFi, GameFi, RWA, L2...)? "
            f"3) O ativo está sendo acumulado por grandes players (whales)? "
            f"4) Existe correlação com Bitcoin ou é independente? "
            f"5) Qual o momentum atual: acelerando ou desacelerando?"
        )
        return self._pesquisar(
            query, search_recency_filter="week", max_tokens=700
        )

    def analisar_defi_pool(
        self, protocolo: str, pool: str = ""
    ) -> AnalisePerplexity:
        """Analisa protocolo DeFi/pool: APY real vs inflacionário,
        impermanent loss, auditoria e variação de TVL nas últimas 72h."""
        alvo = f"pool {pool} no protocolo {protocolo}" if pool else f"protocolo DeFi {protocolo}"
        query = (
            f"Analise a {alvo}: "
            f"1) O APY é real (gerado por taxas) ou inflacionário (emissão de token)? "
            f"2) Qual o risco de impermanent loss para os pares da pool? "
            f"3) O protocolo foi auditado e tem seguro (ex: Nexus Mutual)? "
            f"4) Existe risco de exploração de contrato inteligente? "
            f"5) O TVL está crescendo ou caindo nas últimas 72 horas?"
        )
        return self._pesquisar(
            query, search_recency_filter="day", max_tokens=800
        )

    def pesquisa_livre(
        self,
        query: str,
        recencia: str = "day",
        max_tokens: int = 1024,
    ) -> AnalisePerplexity:
        """Pesquisa livre para qualquer consulta ad-hoc ao mercado."""
        return self._pesquisar(
            query, search_recency_filter=recencia, max_tokens=max_tokens
        )

    # ══════════════════════════════════════════════════════════════
    # BLOCO 2 — Relatório Completo Pré-Operação
    # ══════════════════════════════════════════════════════════════

    def gerar_relatorio_pre_operacao(
        self,
        symbol:             str,
        nome_completo:      str = "",
        verificar_contrato: str = "",
        incluir_defi:       bool = False,
        protocolo_defi:     str = "",
        contexto_mercado:   Optional[Dict[str, Any]] = None,
    ) -> RelatorioPreOperacao:
        """
        Due diligence completa antes de operar. Executa 5 análises
        e consolida em um Score de Confiança 0–100 com recomendação final.

        Args:
            symbol             : Ticker do ativo (ex: 'BTC', 'ETH', 'UNI')
            nome_completo      : Nome do projeto (ex: 'Uniswap')
            verificar_contrato : Endereço do contrato para verificação
            incluir_defi       : Se True, inclui análise de protocolo DeFi
            protocolo_defi     : Nome do protocolo DeFi (ex: 'Aave')

        Returns:
            RelatorioPreOperacao com score, sentimento, risco e recomendação
        """
        logger.info("📊 Gerando relatório pré-operação para %s...", symbol)

        noticias = self._pesquisar_com_fallback(
            query=(
                f"Quais são as principais notícias sobre {nome_completo or symbol} ({symbol}) "
                f"nas últimas 24 horas? Classifique cada notícia como POSITIVA, NEGATIVA ou NEUTRA para o preço. "
                f"Destaque qualquer evento crítico como hack, exploit, regulatory action ou listing em exchange."
            ),
            fallback_resposta=(
                "Sem pesquisa web confiável disponível no momento. Trate o fluxo de notícias como neutro até nova confirmação externa."
            ),
            search_recency_filter="day",
            max_tokens=800,
        )
        sentimento_analise = self._pesquisar_com_fallback(
            query=(
                f"Analise o sentimento atual do mercado para {symbol} com base em Twitter/X, Reddit, Telegram e mídia especializada em cripto. "
                f"Classifique como: MUITO_BULLISH, BULLISH, NEUTRO, BEARISH ou MUITO_BEARISH. Justifique com evidências concretas."
            ),
            fallback_resposta="INDEFINIDO. Sem leitura social confiável disponível agora; trate o sentimento como neutro a levemente cauteloso.",
            search_recency_filter="day",
            max_tokens=600,
        )
        fundamentals = self._pesquisar_com_fallback(
            query=(
                f"Faça uma análise fundamentalista de {nome_completo or symbol} ({symbol}): "
                f"1) Qual é a utilidade real do token? 2) A equipe é doxxed e tem credibilidade? "
                f"3) Qual o tokenomics (supply, distribuição, vesting)? 4) Existem parcerias e integrações reais? "
                f"5) Qual o estágio atual do roadmap? Dê uma nota de 1 a 10 para o potencial fundamentalista."
            ),
            fallback_resposta="Nota 5/10. Sem validação web suficiente neste momento; trate os fundamentos como medianos até checagem manual.",
            search_recency_filter="week",
            max_tokens=1000,
            temperature=0.1,
        )
        seguranca = self._pesquisar_com_fallback(
            query=(
                f"Verifique os riscos de segurança de {symbol}{f' (endereço: {verificar_contrato})' if verificar_contrato else ''}: "
                f"1) Existe algum histórico de exploit ou hack? 2) O contrato foi auditado? Por qual empresa? "
                f"3) Existem red flags de rug pull (concentração de tokens, sem lock de liquidez)? "
                f"4) O projeto está em alguma blacklist de scam? Classifique o risco: MUITO_BAIXO, BAIXO, MEDIO, ALTO ou CRITICO."
            ),
            fallback_resposta="MEDIO. Sem verificação web confiável agora; considere risco médio por precaução até auditoria manual.",
            search_recency_filter="week",
            max_tokens=800,
            temperature=0.1,
        )
        narrativa = self._pesquisar_com_fallback(
            query=(
                f"Qual é a narrativa atual de mercado para {symbol}? 1) Em qual fase do ciclo de hype o projeto está? "
                f"2) Qual é a narrativa dominante (AI, DeFi, GameFi, RWA, L2...)? 3) O ativo está sendo acumulado por grandes players (whales)? "
                f"4) Existe correlação com Bitcoin ou é independente? 5) Qual o momentum atual: acelerando ou desacelerando?"
            ),
            fallback_resposta="Narrativa sem confirmação web suficiente. Trate o ativo como dependente do regime geral de mercado até nova leitura.",
            search_recency_filter="week",
            max_tokens=700,
        )

        defi = None
        if incluir_defi and protocolo_defi:
            defi = self.analisar_defi_pool(protocolo_defi)

        contexto = (
            f"SÍMBOLO: {symbol}\n"
            f"NOTÍCIAS: {noticias.resposta[:400]}\n"
            f"SENTIMENTO: {sentimento_analise.resposta[:300]}\n"
            f"FUNDAMENTALS: {fundamentals.resposta[:300]}\n"
            f"SEGURANÇA: {seguranca.resposta[:300]}\n"
            f"NARRATIVA: {narrativa.resposta[:300]}\n"
        )
        contexto += self._formatar_contexto_mercado(contexto_mercado)
        if defi:
            contexto += f"DeFi: {defi.resposta[:300]}\n"

        sentimento = self._extrair_sentimento(sentimento_analise.resposta)
        risco = self._extrair_risco(seguranca.resposta)
        nota_fundamentals = self._extrair_nota_fundamentals(fundamentals.resposta)
        fatores_score = self._calcular_score_deterministico(
            sentimento=sentimento,
            risco=risco,
            fundamentals_score=nota_fundamentals,
            contexto_mercado=contexto_mercado,
        )
        score = fatores_score["score_final"]
        recomendacao = fatores_score["recomendacao"]

        query_resumo = (
            f"Com base nas análises abaixo sobre {symbol}, gere apenas um resumo executivo para trader em 3 a 5 linhas. "
            f"Não calcule score. Use os sinais já consolidados pelo sistema: score={score}, sentimento={sentimento.value}, "
            f"risco={risco.value}, recomendação={recomendacao}. Destaque tese principal, risco dominante e confirmação pendente.\n\n"
            f"DADOS:\n{contexto}"
        )

        consolidado = self._pesquisar_com_fallback(
            query_resumo,
            fallback_resposta=(
                f"Score {score}/100, sentimento {sentimento.value}, risco {risco.value}, recomendação {recomendacao}. "
                "Resumo indisponível por timeout da pesquisa web; valide notícias, segurança e fluxo antes de executar."
            ),
            search_recency_filter="day",
            max_tokens=420,
            temperature=0.1,
        )
        resumo_final = consolidado.resposta

        logger.info("✅ Relatório %s | Score=%d | %s | %s",
                    symbol, score, sentimento.value, recomendacao)

        return RelatorioPreOperacao(
            symbol=symbol, sentimento=sentimento,
            nivel_risco=risco, score_confianca=score,
            recomendacao=recomendacao, noticias=noticias,
            fundamentals=fundamentals,
            seguranca=seguranca, narrativa=narrativa,
            contexto_mercado=contexto_mercado or {},
            fatores_score=fatores_score,
            resumo_final=resumo_final,
        )

    # ══════════════════════════════════════════════════════════════
    # BLOCO 3 — Helpers para Streamlit
    # ══════════════════════════════════════════════════════════════

    def resumo_para_display(
        self, relatorio: RelatorioPreOperacao
    ) -> Dict[str, Any]:
        """Formata relatório para exibição no Streamlit (st.metric, st.info...)."""
        emoji_s = {
            SentimentoMercado.MUITO_BULLISH: "🚀",
            SentimentoMercado.BULLISH:       "📈",
            SentimentoMercado.NEUTRO:        "➡️",
            SentimentoMercado.BEARISH:       "📉",
            SentimentoMercado.MUITO_BEARISH: "💥",
            SentimentoMercado.INDEFINIDO:    "❓",
        }
        emoji_r = {
            NivelRisco.MUITO_BAIXO: "🟢",
            NivelRisco.BAIXO:       "🟡",
            NivelRisco.MEDIO:       "🟠",
            NivelRisco.ALTO:        "🔴",
            NivelRisco.CRITICO:     "⛔",
        }
        cor = {"OPERAR": "success", "AGUARDAR": "warning",
               "NÃO OPERAR": "error", "NAO OPERAR": "error"}

        return {
            "symbol":            relatorio.symbol,
            "score":             relatorio.score_confianca,
            "sentimento":        f"{emoji_s.get(relatorio.sentimento, '❓')} {relatorio.sentimento.value}",
            "risco":             f"{emoji_r.get(relatorio.nivel_risco, '❓')} {relatorio.nivel_risco.value}",
            "recomendacao":      relatorio.recomendacao,
            "cor_recomendacao":  cor.get(relatorio.recomendacao, "info"),
            "resumo":            relatorio.resumo_final,
            "citacoes_noticias": relatorio.noticias.citacoes if relatorio.noticias else [],
            "fatores_score":     relatorio.fatores_score,
            "contexto_mercado":  relatorio.contexto_mercado,
            "timestamp":         relatorio.timestamp,
        }


# ─── Singleton ────────────────────────────────────────────────────

def get_analyst(modelo: str = "sonar-pro") -> PerplexityAnalyst:
    """
    Retorna instância do analista Perplexity.

    Uso no Streamlit:
        from perplexity_analyst import get_analyst
        analyst = get_analyst()
    """
    return PerplexityAnalyst(modelo=modelo)
