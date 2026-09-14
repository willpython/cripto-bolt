
import os
import base64
import re

import groq
import streamlit as st

from apis_cripto import BinanceFuturesAPI, DefiLlamaAPI, CoinMarketCapAPI
from notification import Notificador
from perplexity_analyst import get_analyst
from settings import get_setting

# Mapeamento de nomes comuns para símbolos CMC
_COIN_ALIASES: dict[str, str] = {
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH",
    "solana": "SOL", "sol": "SOL",
    "xrp": "XRP", "ripple": "XRP",
    "bnb": "BNB", "binance coin": "BNB",
    "cardano": "ADA", "ada": "ADA",
    "dogecoin": "DOGE", "doge": "DOGE",
    "polkadot": "DOT", "dot": "DOT",
    "avalanche": "AVAX", "avax": "AVAX",
    "chainlink": "LINK", "link": "LINK",
    "polygon": "POL", "matic": "POL",
    "litecoin": "LTC", "ltc": "LTC",
    "shiba inu": "SHIB", "shib": "SHIB",
    "uniswap": "UNI", "uni": "UNI",
    "stellar": "XLM", "xlm": "XLM",
    "tron": "TRX", "trx": "TRX",
    "near": "NEAR",
    "aptos": "APT", "apt": "APT",
    "sui": "SUI",
    "pepe": "PEPE",
    "toncoin": "TON", "ton": "TON",
}

_INTENCOES_COTACAO = [
    r"cota[çc][aã]o\s+d[eo]\s+(\w[\w\s]*)",
    r"pre[çc]o\s+d[eo]\s+(\w[\w\s]*)",
    r"quanto\s+(?:vale|custa|est[aá])\s+(?:o\s+|a\s+)?(\w[\w\s]*)",
    r"valor\s+(?:atual\s+)?d[eo]\s+(\w[\w\s]*)",
    r"(\w+)\s+(?:hoje|agora|atual|em\s+tempo\s+real)",
    r"(?:me\s+d[eê]|busca|consulta|mostra)\s+(?:a\s+cota[çc][aã]o|o\s+pre[çc]o)\s+(?:d[eo]\s+)?(\w[\w\s]*)",
]

_INTENCOES_RANKING = [
    r"(?:top|maiores?|melhores?)\s+(\d+)\s+(?:cripto(?:moedas?)?|ativos?|moedas?|coins?)",
    r"(?:ranking|lista|classifica[çc][aã]o)\s+(?:das?|das?\s+\d+)?\s*(?:cripto(?:moedas?)?|moedas?|coins?|ativos?)",
    r"quais?\s+(?:s[aã]o\s+)?(?:as?|os?)\s+(?:top\s+)?(\d+)?\s*(?:maiores?|melhores?|principais?)\s*(?:cripto(?:moedas?)?|moedas?|coins?|ativos?)",
    r"(?:cripto(?:moedas?)?|moedas?)\s+(?:mais\s+)?(?:valiosas?|capitalizadas?|populares?)",
    r"mercado\s+(?:de\s+cripto(?:moedas?)?\s+)?(?:hoje|agora|atual)",
]

_INTENCOES_METADATA = [
    r"o\s+que\s+[eé]\s+(?:o\s+|a\s+)?(\w[\w\s]*?)(?:\?|$|\s+e\s+para|\s+serve|\s+funciona)",
    r"para\s+que\s+serve\s+(?:o\s+|a\s+)?(\w[\w\s]*)",
    r"como\s+funciona\s+(?:o\s+|a\s+)?(\w[\w\s]*)",
    r"me\s+fale\s+(?:sobre|do|da|de)\s+(?:o\s+|a\s+)?(\w[\w\s]*)",
    r"informa[çc][oõ]es\s+(?:sobre|do|da|de)\s+(?:o\s+|a\s+)?(\w[\w\s]*)",
    r"hist[oó]ria\s+(?:do|da|de)\s+(?:o\s+|a\s+)?(\w[\w\s]*)",
]

_INTENCOES_ANALISE_APROFUNDADA = [
    r"(?:analise|an[aá]lise|analisa|avali[ea]|relat[oó]rio)\s+(?:completa|profunda|avancada|t[eé]cnica|fundamentalista|pr[eé]-opera[cç][aã]o)?",
    r"(?:vale\s+a\s+pena\s+operar|vale\s+a\s+pena\s+entrar)",
    r"(?:sentimento|narrativa|fundamentals?|fundamentos|seguran[cç]a)\s+(?:do|da|de)?",
    r"(?:devo\s+operar|posso\s+operar|devo\s+entrar|melhor\s+entrada)",
    r"(?:due\s+diligence|setup\s+de\s+opera[cç][aã]o)",
]

_INTENCOES_ENVIO_EMAIL = [
    r"envia[r]?\s+(?:isso|esse|esta|essa|o\s+relat[oó]rio|a\s+an[aá]lise)?\s*(?:por\s+)?e-?mail",
    r"manda[r]?\s+(?:isso|esse|essa|o\s+relat[oó]rio|a\s+an[aá]lise)?\s*(?:por\s+)?e-?mail",
    r"receber\s+(?:isso|o\s+relat[oó]rio|a\s+an[aá]lise)\s+por\s+e-?mail",
]

# Mapeamento de nomes para slugs da DeFiLlama
_DEFI_PROTOCOL_SLUGS: dict[str, str] = {
    "uniswap": "uniswap",
    "aave": "aave",
    "curve": "curve",
    "compound": "compound",
    "makerdao": "makerdao",
    "maker": "makerdao",
    "lido": "lido",
    "pancakeswap": "pancakeswap",
    "sushiswap": "sushiswap",
    "balancer": "balancer",
    "yearn": "yearn-finance",
    "yearn finance": "yearn-finance",
    "convex": "convex-finance",
    "frax": "frax",
    "gmx": "gmx",
    "dydx": "dydx",
    "synthetix": "synthetix",
    "instadapp": "instadapp",
    "jupiter": "jupiter",
    "raydium": "raydium",
}

# Mapeamento de nomes para slugs de chains da DeFiLlama
_DEFI_CHAIN_SLUGS: dict[str, str] = {
    "ethereum": "Ethereum",
    "eth": "Ethereum",
    "solana": "Solana",
    "sol": "Solana",
    "bsc": "BSC",
    "bnb chain": "BSC",
    "binance smart chain": "BSC",
    "polygon": "Polygon",
    "matic": "Polygon",
    "avalanche": "Avalanche",
    "avax": "Avalanche",
    "arbitrum": "Arbitrum",
    "optimism": "Optimism",
    "base": "Base",
    "tron": "Tron",
    "trx": "Tron",
    "sui": "Sui",
    "near": "Near",
    "aptos": "Aptos",
    "fantom": "Fantom",
    "ftm": "Fantom",
    "cronos": "Cronos",
    "zkSync": "zkSync Era",
}

_INTENCOES_TVL_PROTOCOLO = [
    r"tvl\s+(?:d[eo]\s+)?(?:o\s+|a\s+)?(\w[\w\s]*)",
    r"(?:total\s+value\s+locked|valor\s+(?:total\s+)?bloqueado)\s+(?:d[eo]\s+)?(?:o\s+|a\s+)?(\w[\w\s]*)",
    r"quanto\s+(?:est[aá]\s+bloqueado|tem\s+bloqueado|vale)\s+(?:em\s+)?(?:o\s+|a\s+)?(\w[\w\s]*)",
    r"liquidez\s+(?:d[eo]\s+)?(?:o\s+|a\s+)?protocolo\s+(\w[\w\s]*)",
]

_INTENCOES_TVL_CHAIN = [
    r"tvl\s+(?:d[aeo]\s+)?(?:rede\s+|blockchain\s+|chain\s+)?(\w[\w\s]*?)(?:\?|$|\s+hoje|\s+agora)",
    r"(?:rede|blockchain|chain)\s+(\w[\w\s]*?)\s+(?:tvl|total\s+value|valor\s+bloqueado)",
    r"quanto\s+(?:est[aá]\s+bloqueado|tem)\s+(?:na\s+rede\s+|na\s+chain\s+|em\s+)?(\w[\w\s]*)",
    r"ecosistema\s+(?:d[aeo]\s+)?(\w[\w\s]*)",
]

_INTENCOES_STABLECOINS = [
    r"stablecoin[s]?(?:\s+mais\s+(?:usadas?|populares?|capitalizadas?))?",
    r"(?:quais?|lista|mostre?)\s+(?:as?|os?)?\s*stablecoin[s]?",
    r"(?:usdt|usdc|dai|busd|frax|tusd|usdp)\s+(?:hoje|agora|atual|capitaliza[çc][aã]o|supply)",
    r"mercado\s+de\s+stablecoin[s]?",
    r"stablecoin[s]?\s+(?:mais\s+)?(?:usadas?|populares?|do\s+mercado)",
]

# ─── Intenções LP / Pools de Liquidez ─────────────────────────────────────────
_INTENCOES_LP = [
    r"(?:melhor|melhores?|top|principais?)\s+(?:pool[s]?|lp[s]?|liquidez)",
    r"pool[s]?\s+(?:de\s+)?(?:liquidez|lp)",
    r"(?:criar?|abrir?|montar?|fazer?)\s+(?:uma?\s+)?(?:pool|lp|posi[çc][aã]o)",
    r"(?:yield|rendimento|apy|apr)\s+(?:de\s+)?(?:pool|lp|liquidity|liquidez)",
    r"impermanent\s+loss",
    r"(?:fornecer?|prover?|adicionar?)\s+liquidez",
    r"(?:pool|lp)[s]?\s+(?:eth|btc|sol|bnb|usdc|usdt|dai|wbtc|matic|avax|arb|op)",
    r"(?:eth|btc|sol|bnb|usdc|wbtc|matic|avax|arb|op)\s*[/\-]\s*(?:eth|btc|sol|bnb|usdc|usdt|dai|wbtc|matic|avax|arb|op)",
    r"uniswap\s+(?:v[23]?\s+)?(?:pool|lp|liquidez|yield|apy)",
    r"(?:melhores?|top)\s+(?:pools?|oportunidades?)\s+(?:defi|uniswap|farming)",
    r"farming\s+(?:de\s+)?(?:liquidez|lp|pool)",
    r"(?:analise?|an[aá]lise?|avalie?|verificar?)\s+(?:pool|lp|liquidez)",
]

# Mapeamento de tokens mencionados no LP
_LP_TOKEN_ALIASES: dict[str, str] = {
    "ethereum": "ETH", "eth": "ETH", "bitcoin": "WBTC", "btc": "WBTC", "wbtc": "WBTC",
    "solana": "SOL", "sol": "SOL", "bnb": "BNB", "usdc": "USDC", "usdt": "USDT",
    "dai": "DAI", "matic": "MATIC", "polygon": "MATIC", "avalanche": "AVAX", "avax": "AVAX",
    "arbitrum": "ARB", "arb": "ARB", "optimism": "OP", "op": "OP",
    "chainlink": "LINK", "link": "LINK", "uniswap": "UNI", "uni": "UNI",
    "aave": "AAVE", "pepe": "PEPE", "shib": "SHIB", "shiba": "SHIB",
}

# ─── Intents: Calculadora de IL ──────────────────────────────────────────────
_INTENCOES_IL_CALC = [
    r"(?:calcul[ae]r?|calcula|quanto\s+[eé]|qual\s+[eé])\s+(?:o\s+)?(?:impermanent\s+loss|il\b)",
    r"impermanent\s+loss\s+(?:de|se|com|para)\b",
    r"(?:entrei|entrada)\s+(?:a|em|por|ao?\s+pre[cç]o\s+de?)[\s\$]*[\d]",
    r"il\s+(?:de|se|com|para)\b",
    r"(?:perda|loss)\s+(?:de\s+)?lp\b",
    r"impermanent\s+loss.*\d",
]

# ─── Intents: Range Optimizer ─────────────────────────────────────────────────
_INTENCOES_RANGE_OPT = [
    r"(?:melhor|ideal|sugerir?|sugest[aã]o)\s+(?:de\s+)?(?:faixa|range|limite[s]?)",
    r"(?:faixa|range)\s+(?:de\s+pre[cç]o[s]?|ideal|sugerida?|otimizada?|recomendada?)",
    r"(?:uniswap\s+v3|v3)\s+(?:faixa|range|limite[s]?|pre[cç]o[s]?|liquidez)",
    r"range\s+optimizer\b",
    r"(?:qual|que)\s+(?:faixa|range)\s+(?:usar?|definir?|colocar?|configurar?|colocar?)\b",
    r"(?:concentrar?|concentra[çc][aã]o)\s+(?:de\s+)?liquidez\s+v3",
    r"(?:limite[s]?|bound[s]?)\s+(?:de\s+pre[cç]o|inferior|superior)\s+(?:para\s+)?(?:uniswap|v3|lp)",
]


def _detectar_intencao_il_calc(prompt: str) -> tuple[float, float, float] | None:
    """Detecta cálculo de IL com números explícitos. Retorna (entrada, atual, capital)."""
    texto = prompt.lower()
    if not any(re.search(p, texto) for p in _INTENCOES_IL_CALC):
        return None
    nums = [float(n.replace(",", "."))
            for n in re.findall(r"\b\d+(?:[.,]\d+)?\b", texto)]
    if len(nums) < 2:
        return None
    entrada = nums[0]
    atual = nums[1]
    capital = nums[2] if len(nums) >= 3 else 1000.0
    if entrada <= 0 or atual <= 0:
        return None
    return entrada, atual, capital


def _detectar_intencao_range_opt(prompt: str) -> str | None:
    """Detecta pedido de range optimizer. Retorna símbolo do token ou None."""
    texto = prompt.lower()
    if not any(re.search(p, texto) for p in _INTENCOES_RANGE_OPT):
        return None
    for alias, sym in _LP_TOKEN_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", texto):
            return sym
    for alias, sym in _COIN_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", texto):
            return sym
    return None


def _detectar_protocolo_defi(prompt: str) -> str | None:
    """Detecta intenção de TVL de protocolo DeFi e retorna o slug."""
    texto = prompt.lower().strip()
    for pattern in _INTENCOES_TVL_PROTOCOLO:
        m = re.search(pattern, texto)
        if m:
            candidato = m.group(1).strip().rstrip("?.,!")
            if candidato in _DEFI_PROTOCOL_SLUGS:
                return _DEFI_PROTOCOL_SLUGS[candidato]
            for nome, slug in _DEFI_PROTOCOL_SLUGS.items():
                if nome in candidato or candidato in nome:
                    return slug
    # Fallback: verifica menção direta ao protocolo + tvl/liquidez
    if any(kw in texto for kw in ["tvl", "bloqueado", "liquidez", "protocolo"]):
        for nome, slug in _DEFI_PROTOCOL_SLUGS.items():
            if re.search(rf"\b{re.escape(nome)}\b", texto):
                return slug
    return None


def _detectar_chain_defi(prompt: str) -> str | None:
    """Detecta intenção de TVL de uma blockchain e retorna o nome da chain."""
    texto = prompt.lower().strip()
    for pattern in _INTENCOES_TVL_CHAIN:
        m = re.search(pattern, texto)
        if m:
            candidato = m.group(1).strip().rstrip("?.,!")
            if candidato in _DEFI_CHAIN_SLUGS:
                return _DEFI_CHAIN_SLUGS[candidato]
            for alias, chain in _DEFI_CHAIN_SLUGS.items():
                if alias in candidato or candidato in alias:
                    return chain
    return None


def _detectar_intencao_stablecoins(prompt: str) -> bool:
    """Detecta se o prompt pede informações sobre stablecoins."""
    texto = prompt.lower().strip()
    return any(re.search(p, texto) for p in _INTENCOES_STABLECOINS)


def _detectar_intencao_lp(prompt: str) -> str | None:
    """Detecta se o prompt pede análise de LP/pool. Retorna query de par ou 'geral'."""
    texto = prompt.lower().strip()
    if not any(re.search(p, texto) for p in _INTENCOES_LP):
        return None
    # Tenta extrair par explícito (ex: "ETH/USDC", "ETH-USDT")
    m = re.search(
        r"([a-z]+)\s*[/\-]\s*([a-z]+)",
        texto,
    )
    if m:
        t1 = _LP_TOKEN_ALIASES.get(m.group(1), m.group(1).upper())
        t2 = _LP_TOKEN_ALIASES.get(m.group(2), m.group(2).upper())
        return f"{t1}/{t2}"
    # Tenta extrair token único (ex: "pool de ETH")
    for alias, sym in _LP_TOKEN_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", texto):
            return sym
    return "geral"


_CARD_CSS = (
    "<style>"
    ".cb{background:linear-gradient(135deg,#0d1b2a,#112030);"
    "border:1px solid rgba(0,188,212,.3);border-left:4px solid #00bcd4;"
    "border-radius:12px;padding:16px 20px;margin:6px 0;"
    "font-family:'Segoe UI',Arial,sans-serif;color:#dde4ed;}"
    ".cb-hdr{display:flex;align-items:center;gap:8px;"
    "padding-bottom:10px;margin-bottom:12px;"
    "border-bottom:1px solid rgba(0,188,212,.18);}"
    ".cb-sym{color:#00bcd4;font-size:1.05rem;font-weight:700;}"
    ".cb-name{color:#7a8fa6;font-size:.82rem;}"
    ".cb-badge{margin-left:auto;background:#00bcd4;color:#000;"
    "font-size:.68rem;padding:3px 9px;border-radius:20px;"
    "font-weight:700;white-space:nowrap;}"
    ".cb-lbl{color:#6b7d8f;font-size:.68rem;text-transform:uppercase;"
    "letter-spacing:1.2px;margin-bottom:3px;}"
    ".cb-big{color:#fff;font-size:1.85rem;font-weight:700;"
    "letter-spacing:-.5px;margin-bottom:14px;}"
    ".cb-g3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;}"
    ".cb-g2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;}"
    ".cb-cell{background:rgba(0,0,0,.22);border-radius:8px;padding:9px 8px;text-align:center;}"
    ".cb-clbl{color:#6b7d8f;font-size:.67rem;margin-bottom:4px;}"
    ".cb-cval{font-size:.92rem;font-weight:600;}"
    ".up{color:#4caf50;}.dn{color:#ef5350;}"
    ".cb-foot{margin-top:10px;text-align:right;color:#3d5166;font-size:.63rem;}"
    ".cb-tbl{width:100%;border-collapse:collapse;font-size:.8rem;}"
    ".cb-tbl th{color:#00bcd4;font-size:.67rem;text-transform:uppercase;"
    "letter-spacing:.8px;padding:5px 8px;"
    "border-bottom:1px solid rgba(0,188,212,.25);text-align:left;}"
    ".cb-tbl td{padding:7px 8px;"
    "border-bottom:1px solid rgba(255,255,255,.04);vertical-align:middle;}"
    ".cb-tbl tr:last-child td{border-bottom:none;}"
    ".cb-desc{font-size:.8rem;color:#8fa3b1;line-height:1.5;margin-top:8px;"
    "border-top:1px solid rgba(0,188,212,.12);padding-top:8px;}"
    "</style>"
)


def _fmt_usd(v: float) -> str:
    if v >= 1e12:
        return f"US$ {v / 1e12:.2f}T"
    if v >= 1e9:
        return f"US$ {v / 1e9:.2f}B"
    if v >= 1e6:
        return f"US$ {v / 1e6:.2f}M"
    if v >= 1e3:
        return f"US$ {v / 1e3:.2f}K"
    return f"US$ {v:,.4f}"


def _vc(v: float) -> str:
    return "up" if v >= 0 else "dn"


def _va(v: float) -> str:
    return "▲" if v >= 0 else "▼"


def _html_cotacao(nome, sym, preco, v1h, v24h, v7d, vol, mkt, rank) -> str:
    g3 = (
        f'<div class="cb-cell"><div class="cb-clbl">1 hora</div>'
        f'<div class="cb-cval {_vc(v1h)}">{_va(v1h)} {abs(v1h):.2f}%</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">24 horas</div>'
        f'<div class="cb-cval {_vc(v24h)}">{_va(v24h)} {abs(v24h):.2f}%</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">7 dias</div>'
        f'<div class="cb-cval {_vc(v7d)}">{_va(v7d)} {abs(v7d):.2f}%</div></div>'
    )
    g2 = (
        f'<div class="cb-cell"><div class="cb-clbl">📊 Volume 24h</div>'
        f'<div class="cb-cval" style="color:#e0e0e0">{_fmt_usd(vol)}</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">🏦 Market Cap</div>'
        f'<div class="cb-cval" style="color:#e0e0e0">{_fmt_usd(mkt)}</div></div>'
    )
    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">◈ {sym}</span>'
        f'<span class="cb-name">{nome}</span>'
        f'<span class="cb-badge">Rank #{rank}</span>'
        f'</div>'
        f'<div class="cb-lbl">💵 Preço Atual</div>'
        f'<div class="cb-big">US$ {preco:,.4f}</div>'
        f'<div class="cb-g3">{g3}</div>'
        f'<div class="cb-g2">{g2}</div>'
        f'<div class="cb-foot">🔄 CoinMarketCap · Tempo real</div>'
        f'</div>'
    )


def _html_ranking(moedas: list, limit: int) -> str:
    rows = ""
    for m in moedas:
        rank = m.get("cmc_rank", "?")
        nome = m.get("name", "")
        sym = m.get("symbol", "")
        q = m.get("quote", {}).get("USD", {})
        preco = q.get("price", 0) or 0
        v24h = q.get("percent_change_24h", 0) or 0
        mkt = q.get("market_cap", 0) or 0
        rows += (
            f'<tr>'
            f'<td><span style="color:#00bcd4;font-weight:700">#{rank}</span></td>'
            f'<td><span style="font-weight:600">{nome}</span>'
            f' <span style="color:#6b7d8f;font-size:.75rem">{sym}</span></td>'
            f'<td>US$ {preco:,.4f}</td>'
            f'<td class="{_vc(v24h)}">{_va(v24h)} {abs(v24h):.2f}%</td>'
            f'<td>{_fmt_usd(mkt)}</td>'
            f'</tr>'
        )
    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">🏆 Top {limit} Criptomoedas</span>'
        f'<span class="cb-badge">CoinMarketCap</span>'
        f'</div>'
        f'<table class="cb-tbl"><thead><tr>'
        f'<th>#</th><th>Ativo</th><th>Preço</th><th>24h</th><th>Market Cap</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
        f'<div class="cb-foot">🔄 CoinMarketCap · Tempo real</div>'
        f'</div>'
    )


def _html_metadata(nome, sym, categoria, data_launch, site, whitepaper, descricao) -> str:
    site_html = (
        f'<a href="{site}" target="_blank" style="color:#00bcd4;font-size:.8rem">{site}</a>'
        if site else "N/D"
    )
    wp_div = (
        f'<div style="text-align:right;margin-bottom:6px">'
        f'<a href="{whitepaper}" target="_blank" style="color:#00bcd4;font-size:.78rem">Whitepaper ↗</a>'
        f'</div>'
        if whitepaper else ""
    )
    desc_html = (
        f'<div class="cb-desc">{descricao[:500]}{"..." if len(descricao) > 500 else ""}</div>'
        if descricao else ""
    )
    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">📋 {sym}</span>'
        f'<span class="cb-name">{nome}</span>'
        f'<span class="cb-badge">{categoria}</span>'
        f'</div>'
        f'<div class="cb-g2">'
        f'<div class="cb-cell" style="text-align:left">'
        f'<div class="cb-clbl">📅 Lançamento</div>'
        f'<div class="cb-cval" style="color:#e0e0e0;font-size:.85rem">{data_launch or "N/D"}</div>'
        f'</div>'
        f'<div class="cb-cell" style="text-align:left">'
        f'<div class="cb-clbl">🌐 Site Oficial</div>'
        f'{site_html}'
        f'</div>'
        f'</div>'
        f'{wp_div}'
        f'{desc_html}'
        f'<div class="cb-foot">🔄 CoinMarketCap</div>'
        f'</div>'
    )


def _html_tvl_protocolo(nome, token, categoria, tvl, c1d, c7d, c1m, chains_str, url, desc) -> str:
    url_html = (
        f'<a href="{url}" target="_blank" style="color:#00bcd4;font-size:.78rem">{url}</a>'
        if url else "N/D"
    )
    desc_html = (
        f'<div class="cb-desc">{desc[:400]}{"..." if len(desc) > 400 else ""}</div>'
        if desc else ""
    )
    token_span = f'<span class="cb-name">{token}</span>' if token and token != "N/D" else ""
    g3 = (
        f'<div class="cb-cell"><div class="cb-clbl">1 dia</div>'
        f'<div class="cb-cval {_vc(c1d)}">{_va(c1d)} {abs(c1d):.2f}%</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">7 dias</div>'
        f'<div class="cb-cval {_vc(c7d)}">{_va(c7d)} {abs(c7d):.2f}%</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">30 dias</div>'
        f'<div class="cb-cval {_vc(c1m)}">{_va(c1m)} {abs(c1m):.2f}%</div></div>'
    )
    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">🔗 {nome}</span>'
        f'{token_span}'
        f'<span class="cb-badge">{categoria}</span>'
        f'</div>'
        f'<div class="cb-lbl">🔒 TVL Atual</div>'
        f'<div class="cb-big">{_fmt_usd(tvl)}</div>'
        f'<div class="cb-g3">{g3}</div>'
        f'<div class="cb-cell" style="text-align:left;margin-bottom:8px">'
        f'<div class="cb-clbl">⛓️ Chains</div>'
        f'<div style="font-size:.82rem;color:#b0c4d4">{chains_str}</div>'
        f'</div>'
        f'<div style="margin-bottom:6px;font-size:.78rem">🌐 {url_html}</div>'
        f'{desc_html}'
        f'<div class="cb-foot">🔄 DeFiLlama · Tempo real</div>'
        f'</div>'
    )


def _html_tvl_chain(nome, tvl, c1d, c7d, protocols) -> str:
    g3 = (
        f'<div class="cb-cell"><div class="cb-clbl">1 dia</div>'
        f'<div class="cb-cval {_vc(c1d)}">{_va(c1d)} {abs(c1d):.2f}%</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">7 dias</div>'
        f'<div class="cb-cval {_vc(c7d)}">{_va(c7d)} {abs(c7d):.2f}%</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">Protocolos</div>'
        f'<div class="cb-cval" style="color:#00bcd4">{protocols}</div></div>'
    )
    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">⛓️ {nome}</span>'
        f'<span class="cb-badge">Blockchain</span>'
        f'</div>'
        f'<div class="cb-lbl">🔒 TVL Total</div>'
        f'<div class="cb-big">{_fmt_usd(tvl)}</div>'
        f'<div class="cb-g3">{g3}</div>'
        f'<div class="cb-foot">🔄 DeFiLlama · Tempo real</div>'
        f'</div>'
    )


def _html_stablecoins(moedas: list) -> str:
    rows = ""
    for m in moedas:
        nome = m.get("name", "")
        sym = m.get("symbol", "")
        peg_type = m.get("pegType", "")
        peg_mech = m.get("pegMechanism", "")
        supply = m.get("circulating", {}).get("peggedUSD", 0) or 0
        n_chains = len(m.get("chains", []))
        rows += (
            f'<tr>'
            f'<td><span style="font-weight:600">{nome}</span>'
            f' <span style="color:#6b7d8f;font-size:.72rem">{sym}</span></td>'
            f'<td style="color:#b0c4d4;font-size:.78rem">{peg_type}</td>'
            f'<td style="color:#b0c4d4;font-size:.78rem">{peg_mech}</td>'
            f'<td style="font-weight:600">{_fmt_usd(supply)}</td>'
            f'<td style="color:#00bcd4;text-align:center">{n_chains}</td>'
            f'</tr>'
        )
    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">🪙 Stablecoins</span>'
        f'<span class="cb-badge">DeFiLlama</span>'
        f'</div>'
        f'<table class="cb-tbl"><thead><tr>'
        f'<th>Ativo</th><th>Peg</th><th>Mecanismo</th><th>Supply</th><th>Chains</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
        f'<div class="cb-foot">🔄 DeFiLlama · Tempo real</div>'
        f'</div>'
    )


# ─── LP Intelligence: IL, Score, Range e Card ────────────────────────────────

def _calcular_il(preco_entrada: float, preco_atual: float) -> float:
    """Impermanent Loss (%) pela fórmula fechada de Uniswap V2."""
    if preco_entrada <= 0 or preco_atual <= 0:
        return 0.0
    r = preco_atual / preco_entrada
    il = (2 * r**0.5 / (1 + r)) - 1
    return il * 100


def _range_sugerido(vol_7d_pct: float) -> tuple[str, str]:
    """Sugere perfil de faixa por volatilidade 7d."""
    if vol_7d_pct < 5:
        return "Estreita (±5%)", "Regime lateral — concentre para maximizar fees"
    elif vol_7d_pct < 15:
        return "Média (±15%)", "Volatilidade moderada — equilíbrio entre eficiência e cobertura"
    else:
        return "Larga (±30%+)", "Alta volatilidade — faixa ampla reduz risco de sair do range"


def _score_pool(volume_24h: float, tvl: float, apy_base: float, il_7d: float) -> float:
    """Score LP 0–100: α·(Vol/TVL) + β·APY_base − γ·|IL_7d|"""
    if tvl <= 0:
        return 0.0
    vol_ratio = min(volume_24h / tvl, 1.0)
    apy_norm = min(apy_base / 200, 1.0)
    il_pen = min(abs(il_7d or 0) / 20, 1.0)
    score = (0.50 * vol_ratio + 0.35 * apy_norm - 0.15 * il_pen) * 100
    return round(max(0.0, min(100.0, score)), 1)


def _html_lp_analise(pools: list, query: str) -> str:
    """Card HTML com top pools ranqueadas pelo Score LP."""

    def _score_bar(s: float) -> str:
        cor = "#4caf50" if s >= 60 else ("#ff9800" if s >= 35 else "#ef5350")
        return (
            f'<div style="background:#1a2a3a;border-radius:4px;height:6px;width:100%;margin-top:4px">'
            f'<div style="background:{cor};width:{s}%;height:6px;border-radius:4px"></div></div>'
        )

    rows = ""
    for i, p in enumerate(pools[:5]):
        sym = p.get("symbol", "")
        project = p.get("project", "")
        chain = p.get("chain", "")
        tvl = p.get("tvlUsd", 0) or 0
        apy_base = p.get("apyBase", 0) or 0
        apy_rwd = p.get("apyReward", 0) or 0
        il_7d = p.get("il7d", 0) or 0
        vol_24h = p.get("volumeUsd1d", 0) or 0
        score = _score_pool(vol_24h, tvl, apy_base, il_7d)
        medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i]
        il_class = "dn" if il_7d < -1 else ("up" if il_7d > 0 else "")
        rows += (
            f'<tr>'
            f'<td style="font-size:.8rem">{medal} <b>{sym}</b>'
            f'<br><span style="color:#6b7d8f;font-size:.7rem">{project} · {chain}</span></td>'
            f'<td style="text-align:center">'
            f'<span style="font-weight:700;color:#00bcd4">{score}</span>'
            f'{_score_bar(score)}'
            f'</td>'
            f'<td style="text-align:right">'
            f'<span style="color:#4caf50;font-weight:600">{apy_base:.1f}%</span>'
            f'<br><span style="color:#6b7d8f;font-size:.7rem">+{apy_rwd:.1f}% reward</span></td>'
            f'<td style="text-align:right">{_fmt_usd(tvl)}</td>'
            f'<td style="text-align:right;font-size:.8rem">{_fmt_usd(vol_24h)}</td>'
            f'<td class="{il_class}" style="text-align:right;font-size:.8rem">'
            f'{il_7d:+.2f}%</td>'
            f'</tr>'
        )

    best = pools[0] if pools else {}
    b_vol = best.get("volumeUsd1d", 0) or 0
    b_tvl = best.get("tvlUsd", 1) or 1
    b_vol_ratio = b_vol / b_tvl * 100
    b_il = abs(best.get("il7d", 0) or 0)
    b_range, b_range_desc = _range_sugerido(b_il * 52)

    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">💧 Análise de Pools LP</span>'
        f'<span class="cb-name">{query}</span>'
        f'<span class="cb-badge">DeFiLlama · Yields</span>'
        f'</div>'
        f'<div style="background:rgba(0,188,212,.06);border-radius:8px;padding:8px 12px;'
        f'margin-bottom:12px;font-size:.75rem;color:#7a9ab0">'
        f'📐 <b style="color:#00bcd4">Score LP</b> = '
        f'0.50 × (Vol/TVL) + 0.35 × APY_base − 0.15 × |IL_7d|'
        f'</div>'
        f'<table class="cb-tbl"><thead><tr>'
        f'<th>Pool</th><th>Score</th><th>APY Base</th>'
        f'<th>TVL</th><th>Vol 24h</th><th>IL 7d</th>'
        f'</tr></thead><tbody>{rows}</tbody></table>'
        f'<div class="cb-g2" style="margin-top:12px">'
        f'<div class="cb-cell" style="text-align:left">'
        f'<div class="cb-clbl">📏 Faixa Recomendada</div>'
        f'<div style="font-weight:600;color:#00bcd4;font-size:.9rem">{b_range}</div>'
        f'<div style="font-size:.72rem;color:#7a9ab0;margin-top:3px">{b_range_desc}</div>'
        f'</div>'
        f'<div class="cb-cell" style="text-align:left">'
        f'<div class="cb-clbl">⚡ Vol/TVL (melhor pool)</div>'
        f'<div style="font-weight:600;color:#4caf50;font-size:.9rem">{b_vol_ratio:.1f}%</div>'
        f'<div style="font-size:.72rem;color:#7a9ab0;margin-top:3px">Eficiência de capital</div>'
        f'</div>'
        f'</div>'
        f'<div class="cb-foot">🔄 DeFiLlama Yields · Score = retorno orgânico vs. risco/custo</div>'
        f'</div>'
    )


def _formatar_lp_analise(query: str) -> tuple[str, str] | None:
    """Busca pools na DeFiLlama, ranqueia por Score LP e retorna (html, contexto)."""
    try:
        llama = DefiLlamaAPI()
        data = llama.yields_pools_public()
        pools_raw = data.get("data", []) if isinstance(data, dict) else []
        if not pools_raw:
            return None

        query_up = query.upper()
        if query == "geral":
            filtered = [
                p for p in pools_raw
                if (p.get("tvlUsd") or 0) > 500_000
                and (p.get("volumeUsd1d") or 0) > 0
                and (p.get("apyBase") or 0) > 0
            ]
        else:
            tokens = [t.strip() for t in re.split(r"[/\-]", query_up)]
            filtered = [
                p for p in pools_raw
                if all(t in (p.get("symbol") or "").upper() for t in tokens)
                and (p.get("tvlUsd") or 0) > 100_000
            ]
            if not filtered and len(tokens) == 1:
                filtered = [
                    p for p in pools_raw
                    if tokens[0] in (p.get("symbol") or "").upper()
                    and (p.get("tvlUsd") or 0) > 100_000
                ]

        if not filtered:
            return None

        scored = sorted(
            filtered,
            key=lambda p: _score_pool(
                p.get("volumeUsd1d") or 0,
                p.get("tvlUsd") or 1,
                p.get("apyBase") or 0,
                p.get("il7d") or 0,
            ),
            reverse=True,
        )[:5]

        html = _html_lp_analise(
            scored, query_up if query != "geral" else "Top Pools DeFi")
        best = scored[0]
        context = (
            f"[INSTRUÇÃO: O card de análise de pools LP já foi exibido visualmente. "
            f"Forneça APENAS 2-3 parágrafos: explique o que o Score LP significa, "
            f"comente o perfil de risco da melhor pool e dê uma dica prática para o iniciante. Não repita números.]\n"
            f"Melhor pool: {best.get('symbol', '')} | Projeto: {best.get('project', '')} | "
            f"Chain: {best.get('chain', '')} | APY base: {best.get('apyBase', 0) or 0:.1f}% | "
            f"TVL: {_fmt_usd(best.get('tvlUsd', 0) or 0)} | "
            f"IL 7d: {best.get('il7d', 0) or 0:.2f}%"
        )
        return html, context
    except Exception:
        return None


# ─── HTML + Formatter: Calculadora IL ────────────────────────────────────────

def _html_il_calc(
    preco_entrada: float, preco_atual: float, capital: float,
    il_pct: float, valor_lp: float, valor_hodl: float, perda_usd: float,
) -> str:
    il_cor = "#4caf50" if il_pct > - \
        1 else ("#ff9800" if il_pct > -5 else "#ef5350")
    il_label = "Baixo risco" if il_pct > - \
        1 else ("Atenção" if il_pct > -5 else "Alto risco")
    variacao_preco = (preco_atual / preco_entrada - 1) * 100
    r = preco_atual / preco_entrada
    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">📐 Impermanent Loss</span>'
        f'<span class="cb-name">Entrada: {_fmt_usd(preco_entrada)} → Atual: {_fmt_usd(preco_atual)}</span>'
        f'<span class="cb-badge">{il_label}</span>'
        f'</div>'
        f'<div class="cb-lbl">📉 Impermanent Loss</div>'
        f'<div class="cb-big" style="color:{il_cor}">{il_pct:.2f}%</div>'
        f'<div class="cb-g3">'
        f'<div class="cb-cell"><div class="cb-clbl">📈 Variação do Preço</div>'
        f'<div class="cb-cval {_vc(variacao_preco)}">{_va(variacao_preco)} {abs(variacao_preco):.1f}%</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">💰 Valor na LP</div>'
        f'<div class="cb-cval" style="color:#00bcd4">{_fmt_usd(valor_lp)}</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">🧊 Valor Hodl</div>'
        f'<div class="cb-cval" style="color:#e0e0e0">{_fmt_usd(valor_hodl)}</div></div>'
        f'</div>'
        f'<div class="cb-g2">'
        f'<div class="cb-cell" style="text-align:left"><div class="cb-clbl">💸 Perda vs Hodl</div>'
        f'<div style="font-weight:700;color:{il_cor};font-size:1.1rem">{_fmt_usd(perda_usd)}</div></div>'
        f'<div class="cb-cell" style="text-align:left"><div class="cb-clbl">📊 Razão de Preço (r)</div>'
        f'<div style="font-weight:700;color:#e0e0e0;font-size:1.1rem">{r:.4f}×</div></div>'
        f'</div>'
        f'<div class="cb-foot">🔄 Fórmula: IL = (2√r / (1+r)) − 1 · Uniswap V2</div>'
        f'</div>'
    )


def _formatar_il_calc(preco_entrada: float, preco_atual: float, capital: float) -> tuple[str, str] | None:
    """Calcula IL localmente e retorna (html, contexto)."""
    try:
        il_pct = _calcular_il(preco_entrada, preco_atual)
        r = preco_atual / preco_entrada
        valor_lp = capital * (2 * r ** 0.5 / (1 + r))
        valor_hodl = capital * (0.5 + 0.5 * r)
        perda_usd = valor_lp - valor_hodl
        html = _html_il_calc(preco_entrada, preco_atual,
                             capital, il_pct, valor_lp, valor_hodl, perda_usd)
        context = (
            f"[INSTRUÇÃO: O card de Impermanent Loss já foi exibido. "
            f"Em 2-3 frases explique o que esses números significam na prática e quando as fees compensam o IL. "
            f"Não repita os valores numéricos do card.]\n"
            f"IL: {il_pct:.2f}% | Valor LP: {_fmt_usd(valor_lp)} | "
            f"Valor Hodl: {_fmt_usd(valor_hodl)} | Perda: {_fmt_usd(perda_usd)}"
        )
        return html, context
    except Exception:
        return None


# ─── HTML + Formatter: Range Optimizer ───────────────────────────────────────

def _html_range_opt(
    simbolo: str, preco: float, vol_7d: float,
    faixa: str, desc: str, cor: str,
    preco_min: float, preco_max: float,
    prob_in_range: float, fee_diaria_est: float, capital: float,
) -> str:
    return (
        _CARD_CSS
        + f'<div class="cb">'
        f'<div class="cb-hdr">'
        f'<span class="cb-sym">📏 {simbolo} — Range Optimizer</span>'
        f'<span class="cb-name">Uniswap V3 · baseado em volatilidade 7d</span>'
        f'<span class="cb-badge">CoinMarketCap</span>'
        f'</div>'
        f'<div class="cb-lbl">💵 Preço Atual</div>'
        f'<div class="cb-big">{_fmt_usd(preco)}</div>'
        f'<div class="cb-g3">'
        f'<div class="cb-cell"><div class="cb-clbl">📉 Limite Inferior</div>'
        f'<div class="cb-cval dn">{_fmt_usd(preco_min)}</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">📈 Limite Superior</div>'
        f'<div class="cb-cval up">{_fmt_usd(preco_max)}</div></div>'
        f'<div class="cb-cell"><div class="cb-clbl">🎯 Prob. In Range</div>'
        f'<div class="cb-cval" style="color:#ff9800">{prob_in_range:.0f}%</div></div>'
        f'</div>'
        f'<div class="cb-g2">'
        f'<div class="cb-cell" style="text-align:left"><div class="cb-clbl">📏 Faixa Sugerida</div>'
        f'<div style="font-weight:700;color:{cor};font-size:.95rem">{faixa}</div>'
        f'<div style="font-size:.72rem;color:#7a9ab0;margin-top:3px">{desc}</div></div>'
        f'<div class="cb-cell" style="text-align:left"><div class="cb-clbl">💸 Fee Diária Est. (cap. {_fmt_usd(capital)})</div>'
        f'<div style="font-weight:700;color:#4caf50;font-size:.95rem">{_fmt_usd(fee_diaria_est)}</div>'
        f'<div style="font-size:.72rem;color:#7a9ab0;margin-top:3px">Fee tier 0.3% (padrão)</div></div>'
        f'</div>'
        f'<div class="cb-cell" style="margin-top:8px;text-align:left">'
        f'<div class="cb-clbl">📊 Volatilidade 7d</div>'
        f'<div style="font-weight:600;color:#ff9800">{vol_7d:.2f}%</div>'
        f'</div>'
        f'<div class="cb-foot">🔄 CoinMarketCap · Volatilidade 7d em tempo real</div>'
        f'</div>'
    )


def _formatar_range_opt(simbolo: str) -> tuple[str, str] | None:
    """Busca volatilidade via CMC e sugere faixa ideal para Uniswap V3."""
    try:
        cmc = CoinMarketCapAPI()
        data = cmc.quotes_latest(simbolo)
        moeda = data.get("data", {}).get(simbolo, [{}])
        if isinstance(moeda, list):
            moeda = moeda[0] if moeda else {}
        elif isinstance(moeda, dict):
            moeda = next(iter(moeda.values()), {})
        quote = moeda.get("quote", {}).get("USD", {})
        preco = quote.get("price", 0) or 0
        vol_7d = abs(quote.get("percent_change_7d", 0) or 0)
        if not preco:
            return None
        faixa, desc, cor = _range_sugerido(vol_7d)
        delta = 0.05 if "Estreita" in faixa else (
            0.15 if "Média" in faixa else 0.30)
        preco_min = preco * (1 - delta)
        preco_max = preco * (1 + delta)
        capital = 1000.0
        vol_ratio_proxy = min(vol_7d * 0.03, 0.5)
        fee_diaria_est = capital * 0.003 * vol_ratio_proxy
        prob_in_range = max(0.3, 1.0 - vol_7d / 100) * 100
        html = _html_range_opt(
            simbolo, preco, vol_7d, faixa, desc, cor,
            preco_min, preco_max, prob_in_range, fee_diaria_est, capital,
        )
        context = (
            f"[INSTRUÇÃO: O card de Range Optimizer para {simbolo} já foi exibido. "
            f"Em 2-3 frases: explique por que a faixa '{faixa}' foi escolhida, "
            f"o que acontece quando o preço sai do range e como monitorar a posição. "
            f"Não repita os valores numéricos do card.]\n"
            f"Símbolo: {simbolo} | Preço: {_fmt_usd(preco)} | Volatilidade 7d: {vol_7d:.1f}% | "
            f"Faixa: {faixa} | Min: {_fmt_usd(preco_min)} | Max: {_fmt_usd(preco_max)}"
        )
        return html, context
    except Exception:
        return None


def _formatar_tvl_protocolo(slug: str) -> tuple[str, str] | None:
    """Busca TVL e dados de um protocolo DeFi na DeFiLlama."""
    try:
        llama = DefiLlamaAPI()
        data = llama.protocol(slug)
        if not data or not isinstance(data, dict):
            return None

        nome = data.get("name", slug)
        tvl_atual = data.get("tvl", 0) or 0
        categoria = data.get("category", "N/D")
        chains = data.get("chains", [])
        chains_str = ", ".join(chains[:5]) if chains else "N/D"
        desc = data.get("description", "") or ""
        change_1d = data.get("change_1d", 0) or 0
        change_7d = data.get("change_7d", 0) or 0
        change_1m = data.get("change_1m", 0) or 0
        token = data.get("symbol", "") or ""
        url = data.get("url", "") or ""

        html = _html_tvl_protocolo(nome, token, categoria, tvl_atual,
                                   change_1d, change_7d, change_1m, chains_str, url, desc)
        context = (
            f"[INSTRUÇÃO: Os dados do protocolo já foram exibidos em um card visual. "
            f"Forneça APENAS um comentário analítico em 2-3 parágrafos sobre o que o TVL indica sobre a saúde e adoção do protocolo.]\n"
            f"Protocolo: {nome} | Categoria: {categoria} | TVL: {_fmt_usd(tvl_atual)} | "
            f"1d: {change_1d:+.2f}% | 7d: {change_7d:+.2f}% | 30d: {change_1m:+.2f}% | Chains: {chains_str}"
        )
        return html, context
    except Exception:
        return None


def _formatar_tvl_chain(chain: str) -> tuple[str, str] | None:
    """Busca TVL de uma blockchain na DeFiLlama."""
    try:
        llama = DefiLlamaAPI()
        chains_data = llama.chains()
        if not isinstance(chains_data, list):
            return None

        chain_info = next((c for c in chains_data if c.get(
            "name", "").lower() == chain.lower()), None)
        if not chain_info:
            return None

        nome = chain_info.get("name", chain)
        tvl = chain_info.get("tvl", 0) or 0
        change_1d = chain_info.get("change_1d", 0) or 0
        change_7d = chain_info.get("change_7d", 0) or 0
        protocols = chain_info.get("protocols", 0) or 0

        html = _html_tvl_chain(nome, tvl, change_1d, change_7d, protocols)
        context = (
            f"[INSTRUÇÃO: Os dados da chain já foram exibidos em um card visual. "
            f"Forneça APENAS um comentário analítico em 2-3 parágrafos explicando o que o TVL da chain indica para um investidor iniciante.]\n"
            f"Blockchain: {nome} | TVL: {_fmt_usd(tvl)} | 1d: {change_1d:+.2f}% | 7d: {change_7d:+.2f}% | Protocolos: {protocols}"
        )
        return html, context
    except Exception:
        return None


def _formatar_stablecoins_defi() -> tuple[str, str] | None:
    """Busca dados das principais stablecoins na DeFiLlama."""
    try:
        llama = DefiLlamaAPI()
        data = llama.stablecoins()
        moedas = data.get("peggedAssets", []) if isinstance(data, dict) else []
        if not moedas:
            return None

        moedas_sorted = sorted(moedas, key=lambda x: x.get(
            "circulating", {}).get("peggedUSD", 0), reverse=True)[:10]
        html = _html_stablecoins(moedas_sorted)
        tops = ", ".join(
            f"{m.get('symbol', '')} ({_fmt_usd(m.get('circulating', {}).get('peggedUSD', 0) or 0)})"
            for m in moedas_sorted[:5]
        )
        context = (
            f"[INSTRUÇÃO: A tabela de stablecoins já foi exibida visualmente. "
            f"Forneça APENAS um comentário analítico explicando as diferenças entre os mecanismos de peg "
            f"(fiat, cripto, algorítmico) e os riscos de cada tipo.]\n"
            f"Top stablecoins por supply: {tops}"
        )
        return html, context
    except Exception:
        return None


def _detectar_simbolo_cotacao(prompt: str) -> str | None:
    texto = prompt.lower().strip()
    for pattern in _INTENCOES_COTACAO:
        m = re.search(pattern, texto)
        if m:
            candidato = m.group(1).strip().rstrip("?.,!")
            if candidato in _COIN_ALIASES:
                return _COIN_ALIASES[candidato]
            for alias, symbol in _COIN_ALIASES.items():
                if alias in candidato or candidato in alias:
                    return symbol
    # Fallback: verifica se qualquer alias aparece solto no texto
    for alias, symbol in _COIN_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", texto):
            return symbol
    return None


def _detectar_intencao_ranking(prompt: str) -> int | None:
    """Detecta se o prompt pede ranking do mercado e retorna o limite (default 10)."""
    texto = prompt.lower().strip()
    for pattern in _INTENCOES_RANKING:
        m = re.search(pattern, texto)
        if m:
            try:
                limit = int(m.group(1)) if m.lastindex and m.group(1) else 10
                return min(max(limit, 5), 20)  # entre 5 e 20
            except (IndexError, TypeError):
                return 10
    return None


def _detectar_simbolo_metadata(prompt: str) -> str | None:
    """Detecta se o prompt pede informações/metadados de uma cripto."""
    texto = prompt.lower().strip()
    for pattern in _INTENCOES_METADATA:
        m = re.search(pattern, texto)
        if m:
            candidato = m.group(1).strip().rstrip("?.,!")
            if candidato in _COIN_ALIASES:
                return _COIN_ALIASES[candidato]
            for alias, symbol in _COIN_ALIASES.items():
                if alias in candidato or candidato in alias:
                    return symbol
    return None


def _detectar_simbolo_analise(prompt: str) -> str | None:
    """Detecta pedidos de análise aprofundada e retorna o símbolo alvo."""
    texto = prompt.lower().strip()
    if not any(re.search(pattern, texto) for pattern in _INTENCOES_ANALISE_APROFUNDADA):
        return None
    return _detectar_simbolo_cotacao(prompt) or _detectar_simbolo_metadata(prompt)


def _detectar_intencao_analise_token(prompt: str) -> str | None:
    if _detectar_intencao_lp(prompt) or _detectar_protocolo_defi(prompt):
        return None
    return _detectar_simbolo_analise(prompt)


def _detectar_intencao_analise_protocolo(prompt: str) -> str | None:
    texto = prompt.lower().strip()
    if not any(re.search(pattern, texto) for pattern in _INTENCOES_ANALISE_APROFUNDADA):
        return None
    return _detectar_protocolo_defi(prompt)


def _detectar_intencao_analise_pool(prompt: str) -> str | None:
    texto = prompt.lower().strip()
    if not any(re.search(pattern, texto) for pattern in _INTENCOES_ANALISE_APROFUNDADA):
        return None
    return _detectar_intencao_lp(prompt)


def _usuario_pediu_envio_email(prompt: str) -> bool:
    texto = prompt.lower().strip()
    return any(re.search(pattern, texto) for pattern in _INTENCOES_ENVIO_EMAIL)


@st.cache_resource(show_spinner=False)
def _get_perplexity_analyst_cached():
    return get_analyst()


def _html_relatorio_inteligencia(display: dict[str, str | int], citacoes: list[str]) -> str:
    score = int(display.get('score', 0) or 0)
    recomendacao = str(display.get('recomendacao', 'AGUARDAR'))
    resumo = str(display.get('resumo', ''))
    sentimento = str(display.get('sentimento', ''))
    risco = str(display.get('risco', ''))
    fatores_score = display.get('fatores_score', {}) or {}
    contexto_mercado = display.get('contexto_mercado', {}) or {}
    fatores_html = ''
    if fatores_score:
        fatores_html = (
            '<div class="cb-desc"><strong>Fatores do score</strong>'
            '<div class="cb-g2" style="margin-top:8px">'
            f'<div class="cb-cell"><div class="cb-clbl">Sentimento</div><div class="cb-cval">{int(fatores_score.get("sentimento", 0)):+}</div></div>'
            f'<div class="cb-cell"><div class="cb-clbl">Risco</div><div class="cb-cval">{int(fatores_score.get("risco", 0)):+}</div></div>'
            f'<div class="cb-cell"><div class="cb-clbl">Fundamentals</div><div class="cb-cval">{int(fatores_score.get("fundamentals", 0)):+}</div></div>'
            f'<div class="cb-cell"><div class="cb-clbl">Contexto</div><div class="cb-cval">{int(fatores_score.get("contexto", 0)):+}</div></div>'
            '</div></div>'
        )
    execucao_html = ''
    if contexto_mercado:
        funding = contexto_mercado.get('funding_rate')
        open_interest = contexto_mercado.get('open_interest_usd')
        spread_bps = contexto_mercado.get('bid_ask_spread_bps')
        imbalance = contexto_mercado.get('order_book_imbalance_ratio')
        if any(v not in (None, '', 0, 0.0) for v in (funding, open_interest, spread_bps, imbalance)):
            funding_text = f"{float(funding) * 100:.4f}%" if funding not in (None, '') else 'N/D'
            oi_text = _fmt_usd(float(open_interest or 0)) if open_interest not in (None, '') else 'N/D'
            spread_text = f"{float(spread_bps):.2f} bps" if spread_bps not in (None, '') else 'N/D'
            imbalance_text = f"{float(imbalance):.2f}x" if imbalance not in (None, '') else 'N/D'
            execucao_html = (
                '<div class="cb-desc"><strong>Execução e derivativos</strong>'
                '<div class="cb-g2" style="margin-top:8px">'
                f'<div class="cb-cell"><div class="cb-clbl">Funding</div><div class="cb-cval">{funding_text}</div></div>'
                f'<div class="cb-cell"><div class="cb-clbl">Open Interest</div><div class="cb-cval">{oi_text}</div></div>'
                f'<div class="cb-cell"><div class="cb-clbl">Spread</div><div class="cb-cval">{spread_text}</div></div>'
                f'<div class="cb-cell"><div class="cb-clbl">Book Imbalance</div><div class="cb-cval">{imbalance_text}</div></div>'
                '</div></div>'
            )
    referencias = ''.join(
        f'<li><a href="{url}" target="_blank" style="color:#7dd3fc">Fonte {idx}</a></li>'
        for idx, url in enumerate(citacoes[:4], start=1)
    )
    referencias_html = (
        '<div class="cb-desc"><strong>Referências</strong><ul style="margin:8px 0 0 18px;">'
        f'{referencias}</ul></div>'
        if referencias else ''
    )
    return (
        _CARD_CSS
        + '<div class="cb">'
        + '<div class="cb-hdr">'
        + '<span class="cb-sym">🧠 Inteligência Perplexity</span>'
        + '<span class="cb-badge">Pré-operação</span>'
        + '</div>'
        + '<div class="cb-g3">'
        + f'<div class="cb-cell"><div class="cb-clbl">Score</div><div class="cb-cval">{score}/100</div></div>'
        + f'<div class="cb-cell"><div class="cb-clbl">Sentimento</div><div class="cb-cval">{sentimento}</div></div>'
        + f'<div class="cb-cell"><div class="cb-clbl">Risco</div><div class="cb-cval">{risco}</div></div>'
        + '</div>'
        + f'<div class="cb-lbl">Recomendação</div><div class="cb-big" style="font-size:1.15rem">{recomendacao}</div>'
        + fatores_html
        + execucao_html
        + f'<div class="cb-desc">{resumo}</div>'
        + referencias_html
        + '<div class="cb-foot">🔎 Perplexity Sonar Pro + Cripto Bolt</div>'
        + '</div>'
    )


def _coletar_contexto_futuros(symbol: str) -> dict[str, str | float] | None:
    try:
        futures = BinanceFuturesAPI()
        futures_symbol = f'{symbol.upper()}USDT'
        mark = futures.mark_price(futures_symbol)
        oi = futures.open_interest(futures_symbol)
        depth = futures.order_book(futures_symbol, limit=20)
        funding_list = futures.funding_rate(futures_symbol, limit=1)

        funding_item = funding_list[0] if isinstance(funding_list, list) and funding_list else {}
        mark_price = float(mark.get('markPrice', 0) or 0)
        open_interest = float(oi.get('openInterest', 0) or 0)
        bids = depth.get('bids', []) if isinstance(depth, dict) else []
        asks = depth.get('asks', []) if isinstance(depth, dict) else []

        best_bid = float(bids[0][0]) if bids else 0.0
        best_ask = float(asks[0][0]) if asks else 0.0
        bid_notional = sum(float(price) * float(qty) for price, qty in bids[:10])
        ask_notional = sum(float(price) * float(qty) for price, qty in asks[:10])
        book_imbalance = (bid_notional / ask_notional) if ask_notional else 1.0
        mid = ((best_bid + best_ask) / 2) if best_bid and best_ask else 0.0
        spread_bps = (((best_ask - best_bid) / mid) * 10000) if mid else 0.0

        return {
            'futures_symbol': futures_symbol,
            'mark_price': mark_price,
            'funding_rate': float(funding_item.get('fundingRate', 0) or 0),
            'open_interest_contracts': open_interest,
            'open_interest_usd': open_interest * mark_price if mark_price else 0.0,
            'bid_ask_spread_bps': spread_bps,
            'order_book_imbalance_ratio': round(book_imbalance, 3),
        }
    except Exception:
        return None


def _coletar_contexto_token(symbol: str) -> dict[str, str | float | int] | None:
    try:
        cmc = CoinMarketCapAPI()
        quote_data = cmc.quotes_latest(symbol)
        metadata_data = cmc.metadata(symbol)
        futures_context = _coletar_contexto_futuros(symbol) or {}

        moeda = quote_data.get('data', {}).get(symbol.upper(), [{}])
        if isinstance(moeda, list):
            moeda = moeda[0] if moeda else {}
        elif isinstance(moeda, dict):
            moeda = next(iter(moeda.values()), {}) if moeda else {}

        meta = metadata_data.get('data', {}).get(symbol.upper(), {})
        if isinstance(meta, list):
            meta = meta[0] if meta else {}

        quote = moeda.get('quote', {}).get('USD', {})
        market_cap = float(quote.get('market_cap', 0) or 0)
        volume_24h = float(quote.get('volume_24h', 0) or 0)
        contexto = {
            'symbol': symbol.upper(),
            'name': moeda.get('name', symbol.upper()),
            'price_usd': float(quote.get('price', 0) or 0),
            'percent_change_1h': float(quote.get('percent_change_1h', 0) or 0),
            'percent_change_24h': float(quote.get('percent_change_24h', 0) or 0),
            'percent_change_7d': float(quote.get('percent_change_7d', 0) or 0),
            'volume_24h': volume_24h,
            'market_cap': market_cap,
            'volume_market_cap_ratio': round(volume_24h / market_cap, 4) if market_cap else 0.0,
            'cmc_rank': moeda.get('cmc_rank', 'N/D'),
            'category': meta.get('category', 'N/D'),
            'date_launched': meta.get('date_launched', 'N/D'),
        }
        contexto.update(futures_context)
        return contexto
    except Exception:
        return None


def _coletar_contexto_protocolo(slug: str) -> dict[str, str | float | int] | None:
    try:
        llama = DefiLlamaAPI()
        data = llama.protocol(slug)
        if not isinstance(data, dict):
            return None
        chains = data.get('chains', []) or []
        return {
            'protocol_slug': slug,
            'protocol_name': data.get('name', slug),
            'category': data.get('category', 'N/D'),
            'tvl': float(data.get('tvl', 0) or 0),
            'tvl_change_1d': float(data.get('change_1d', 0) or 0),
            'tvl_change_7d': float(data.get('change_7d', 0) or 0),
            'tvl_change_1m': float(data.get('change_1m', 0) or 0),
            'chains_count': len(chains),
            'chains': ', '.join(chains[:5]) if chains else 'N/D',
        }
    except Exception:
        return None


def _coletar_contexto_pool(query: str) -> dict[str, str | float | int] | None:
    try:
        llama = DefiLlamaAPI()
        data = llama.yields_pools_public()
        pools_raw = data.get('data', []) if isinstance(data, dict) else []
        if not pools_raw:
            return None

        query_up = query.upper()
        if query == 'geral':
            filtered = [
                p for p in pools_raw
                if (p.get('tvlUsd') or 0) > 500_000
                and (p.get('volumeUsd1d') or 0) > 0
                and (p.get('apyBase') or 0) > 0
            ]
        else:
            tokens = [t.strip() for t in re.split(r'[/\-]', query_up)]
            filtered = [
                p for p in pools_raw
                if all(t in (p.get('symbol') or '').upper() for t in tokens)
                and (p.get('tvlUsd') or 0) > 100_000
            ]
            if not filtered and len(tokens) == 1:
                filtered = [
                    p for p in pools_raw
                    if tokens[0] in (p.get('symbol') or '').upper()
                    and (p.get('tvlUsd') or 0) > 100_000
                ]
        if not filtered:
            return None

        best = max(
            filtered,
            key=lambda p: _score_pool(
                p.get('volumeUsd1d') or 0,
                p.get('tvlUsd') or 1,
                p.get('apyBase') or 0,
                p.get('il7d') or 0,
            ),
        )
        tvl = float(best.get('tvlUsd', 0) or 0)
        vol_24h = float(best.get('volumeUsd1d', 0) or 0)
        return {
            'pool_query': query_up if query != 'geral' else 'TOP POOLS DEFI',
            'pool_symbol': best.get('symbol', ''),
            'protocol_name': best.get('project', ''),
            'chain': best.get('chain', ''),
            'tvl': tvl,
            'volume_24h': vol_24h,
            'volume_market_cap_ratio': round(vol_24h / tvl, 4) if tvl else 0.0,
            'apy_base': float(best.get('apyBase', 0) or 0),
            'apy_reward': float(best.get('apyReward', 0) or 0),
            'pool_score': float(_score_pool(vol_24h, tvl, best.get('apyBase') or 0, best.get('il7d') or 0)),
            'il_7d': float(best.get('il7d', 0) or 0),
        }
    except Exception:
        return None


def _coletar_citacoes_relatorio(relatorio) -> list[str]:
    citacoes = []
    for bloco in (relatorio.noticias, relatorio.fundamentals, relatorio.seguranca, relatorio.narrativa):
        if bloco and bloco.citacoes:
            citacoes.extend(bloco.citacoes)
    return list(dict.fromkeys(citacoes))


def _formatar_fatores_score(fatores: dict[str, str | int | float]) -> str:
    base = fatores.get('base', 50)
    sentimento = fatores.get('sentimento', 0)
    risco = fatores.get('risco', 0)
    fundamentals = fatores.get('fundamentals', 0)
    contexto = fatores.get('contexto', 0)
    return (
        f'Base {base} | Sentimento {sentimento:+} | Risco {risco:+} | '
        f'Fundamentals {fundamentals:+} | Contexto {contexto:+}'
    )


def _formatar_relatorio_perplexity_token(symbol: str) -> tuple[str, str] | None:
    """Gera relatório Perplexity para um token, usando contexto quantitativo do projeto."""
    try:
        analyst = _get_perplexity_analyst_cached()
        contexto = _coletar_contexto_token(symbol) or {}
        relatorio = analyst.gerar_relatorio_pre_operacao(symbol=symbol, contexto_mercado=contexto)
        display = analyst.resumo_para_display(relatorio)
        citacoes = _coletar_citacoes_relatorio(relatorio)
        html = _html_relatorio_inteligencia(display, citacoes)
        fatores = _formatar_fatores_score(display.get('fatores_score', {}))
        context = (
            '[INSTRUÇÃO: O relatório pré-operação já foi exibido visualmente. '
            'Escreva APENAS 2-3 parágrafos curtos com leitura operacional. '
            'Não repita score, sentimento, risco nem recomendação literalmente. '
            'Explique a tese principal, o maior risco e o que faltaria confirmar antes da execução.]\n'
            f"Ativo: {symbol} | Score: {display['score']} | Sentimento: {display['sentimento']} | "
            f"Risco: {display['risco']} | Recomendação: {display['recomendacao']} | Fatores: {fatores} | Resumo: {display['resumo']}"
        )
        return html, context
    except Exception:
        return None


def _formatar_relatorio_perplexity_protocolo(slug: str) -> tuple[str, str] | None:
    """Gera leitura de inteligência para protocolo DeFi com contexto da DeFiLlama."""
    try:
        analyst = _get_perplexity_analyst_cached()
        contexto = _coletar_contexto_protocolo(slug)
        if not contexto:
            return None
        analise = analyst.analisar_defi_pool(str(contexto['protocol_name']))
        titulo = str(contexto['protocol_name'])
        resumo = analise.resposta[:900]
        display = {
            'score': max(0, min(100, int(55 + (6 if float(contexto.get('tvl_change_7d', 0) or 0) > 5 else -6 if float(contexto.get('tvl_change_7d', 0) or 0) < -5 else 0)))),
            'sentimento': '🧭 PROTOCOLO',
            'risco': '🟠 CONTEXTUAL',
            'recomendacao': 'MONITORAR',
            'resumo': resumo,
        }
        html = _html_relatorio_inteligencia(display, analise.citacoes)
        context_text = (
            '[INSTRUÇÃO: A leitura do protocolo já foi exibida visualmente. '
            'Escreva APENAS 2-3 parágrafos com foco em adoção, sustentabilidade do TVL e principal risco estrutural. '
            'Não repita números literalmente.]\n'
            f"Protocolo: {titulo} | TVL: {_fmt_usd(float(contexto.get('tvl', 0) or 0))} | "
            f"1d: {float(contexto.get('tvl_change_1d', 0) or 0):+.2f}% | 7d: {float(contexto.get('tvl_change_7d', 0) or 0):+.2f}% | "
            f"Categoria: {contexto.get('category', 'N/D')} | Chains: {contexto.get('chains', 'N/D')} | Resumo: {resumo}"
        )
        return html, context_text
    except Exception:
        return None


def _formatar_relatorio_perplexity_pool(query: str) -> tuple[str, str] | None:
    """Gera leitura de inteligência para pool/LP com dados locais e pesquisa web."""
    try:
        analyst = _get_perplexity_analyst_cached()
        contexto = _coletar_contexto_pool(query)
        if not contexto:
            return None
        protocolo = str(contexto.get('protocol_name', '') or 'DeFi')
        pool_symbol = str(contexto.get('pool_symbol', '') or query)
        analise = analyst.analisar_defi_pool(protocolo, pool_symbol)
        pool_score = int(round(float(contexto.get('pool_score', 0) or 0)))
        recomendacao = 'OBSERVAR' if pool_score < 65 else 'ESTUDAR ENTRADA'
        resumo = analise.resposta[:900]
        display = {
            'score': pool_score,
            'sentimento': '💧 POOL/LP',
            'risco': '🟠 EXECUÇÃO',
            'recomendacao': recomendacao,
            'resumo': resumo,
        }
        html = _html_relatorio_inteligencia(display, analise.citacoes)
        context_text = (
            '[INSTRUÇÃO: A leitura da pool já foi exibida visualmente. '
            'Escreva APENAS 2-3 parágrafos com foco em qualidade do yield, risco de IL e o que validar antes de prover liquidez. '
            'Não repita os números literalmente.]\n'
            f"Pool: {pool_symbol} | Protocolo: {protocolo} | Chain: {contexto.get('chain', '')} | "
            f"APY base: {float(contexto.get('apy_base', 0) or 0):.2f}% | APY reward: {float(contexto.get('apy_reward', 0) or 0):.2f}% | "
            f"TVL: {_fmt_usd(float(contexto.get('tvl', 0) or 0))} | Vol 24h: {_fmt_usd(float(contexto.get('volume_24h', 0) or 0))} | "
            f"IL 7d: {float(contexto.get('il_7d', 0) or 0):+.2f}% | Score local: {pool_score} | Resumo: {resumo}"
        )
        return html, context_text
    except Exception:
        return None


def _formatar_relatorio_perplexity(symbol: str) -> tuple[str, str] | None:
    return _formatar_relatorio_perplexity_token(symbol)


def _formatar_cotacao_cmc(symbol: str) -> tuple[str, str] | None:
    """Busca cotação em tempo real na CoinMarketCap."""
    try:
        cmc = CoinMarketCapAPI()
        data = cmc.quotes_latest(symbol)
        moeda = data.get("data", {}).get(symbol.upper(), [{}])
        if isinstance(moeda, list):
            moeda = moeda[0] if moeda else {}
        elif isinstance(moeda, dict):
            moeda = next(iter(moeda.values()), {}) if moeda else {}

        nome = moeda.get("name", symbol)
        quote = moeda.get("quote", {}).get("USD", {})
        preco = quote.get("price")
        if preco is None:
            return None

        v1h = quote.get("percent_change_1h", 0) or 0
        v24h = quote.get("percent_change_24h", 0) or 0
        v7d = quote.get("percent_change_7d", 0) or 0
        vol = quote.get("volume_24h", 0) or 0
        mkt = quote.get("market_cap", 0) or 0
        rank = moeda.get("cmc_rank", "N/D")

        html = _html_cotacao(nome, symbol.upper(), preco,
                             v1h, v24h, v7d, vol, mkt, rank)
        context = (
            f"[INSTRUÇÃO: Os dados já foram exibidos em um card visual. Forneça APENAS um comentário analítico "
            f"objetivo em 2-3 parágrafos sobre o momento do ativo. Não repita os números.]\n"
            f"{nome} ({symbol.upper()}) | Preço: US$ {preco:,.4f} | 1h: {v1h:+.2f}% | "
            f"24h: {v24h:+.2f}% | 7d: {v7d:+.2f}% | Vol: {_fmt_usd(vol)} | MCap: {_fmt_usd(mkt)} | Rank: #{rank}"
        )
        return html, context
    except Exception:
        return None


def _formatar_ranking_cmc(limit: int = 10) -> tuple[str, str] | None:
    """Busca o ranking das top N criptomoedas na CoinMarketCap."""
    try:
        cmc = CoinMarketCapAPI()
        data = cmc.listings_latest(limit=limit)
        moedas = data.get("data", [])
        if not moedas:
            return None

        html = _html_ranking(moedas, limit)
        tops3 = sorted(
            moedas,
            key=lambda x: x.get("quote", {}).get(
                "USD", {}).get("percent_change_24h", 0) or 0,
            reverse=True
        )[:3]
        tops3_str = ", ".join(
            f"{m.get('symbol', '')} ({(m.get('quote', {}).get('USD', {}).get('percent_change_24h', 0) or 0):+.2f}%)"
            for m in tops3
        )
        context = (
            f"[INSTRUÇÃO: O ranking já foi exibido em uma tabela visual. Forneça APENAS um comentário analítico "
            f"sobre o estado geral do mercado. Destaque as 3 com melhor desempenho nas últimas 24h.]\n"
            f"Top 3 desempenho 24h: {tops3_str}"
        )
        return html, context
    except Exception:
        return None


def _formatar_metadata_cmc(symbol: str) -> tuple[str, str] | None:
    """Busca metadados/informações de uma cripto na CoinMarketCap."""
    try:
        cmc = CoinMarketCapAPI()
        data = cmc.metadata(symbol)
        moedas = data.get("data", {})
        moeda = moedas.get(symbol.upper())
        if isinstance(moeda, list):
            moeda = moeda[0] if moeda else {}
        if not moeda:
            return None

        nome = moeda.get("name", symbol)
        descricao = moeda.get("description", "Sem descrição disponível.")
        categoria = moeda.get("category", "N/D")
        data_launch = moeda.get("date_launched") or "N/D"
        urls = moeda.get("urls", {})
        site = urls.get("website", [""])[0] if urls.get("website") else ""
        whitepaper = urls.get("technical_doc", [""])[
            0] if urls.get("technical_doc") else ""

        html = _html_metadata(nome, symbol.upper(), categoria,
                              data_launch, site, whitepaper, descricao)
        context = (
            f"[INSTRUÇÃO: Os metadados já foram exibidos em um card visual. Forneça APENAS um comentário analítico "
            f"em 2-3 parágrafos explicando o papel deste ativo no mercado cripto de forma didática para iniciantes.]\n"
            f"Ativo: {nome} ({symbol.upper()}) | Categoria: {categoria} | Lançamento: {data_launch}"
        )
        return html, context
    except Exception:
        return None


def _get_groq_api_key() -> str | None:
    return get_setting('GROQ_API_KEY')


def buscar_protocolos_defi():
    defi_llama_api = DefiLlamaAPI()
    try:
        protocolos = defi_llama_api.protocols()
        return [p['name'] for p in protocolos[:5]]
    except Exception as e:
        return [f'Erro ao consultar protocolos: {e}']


def showCryptoBot():
    if 'image' not in st.session_state:
        st.session_state.image = None

    # ── IMAGEM COM ANIMAÇÃO NO TOPO ──
    from utils import img_to_base64
    img_path = "src/img/cripto-bolt.png"
    img_base64 = img_to_base64(img_path)
    st.markdown(
        f"""
        <style>
        @keyframes pulse {{
            0%, 100% {{
                transform: scale(1);
                opacity: 1;
                box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.26);
            }}
            50% {{
                transform: scale(1.08);
                opacity: 0.95;
                box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.42), 0 0 35px rgba(23, 190, 187, 0.5);
            }}
        }}
        .crypto-bot-header {{
            display: flex;
            flex-direction: column;
            align-items: center;
            margin: 1rem 0 2rem 0;
        }}
        .crypto-bot-avatar {{
            border-radius: 50%;
            box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(23, 190, 187, 0.26);
            animation: pulse 2.5s ease-in-out infinite;
            transition: transform 0.3s ease, box-shadow 0.4s ease;
        }}
        .crypto-bot-avatar:hover {{
            transform: scale(1.1);
            box-shadow: 0 0 0 8px rgba(255,255,255,0.58), 0 22px 56px rgba(255, 159, 28, 0.5), 0 0 50px rgba(255, 159, 28, 0.6), inset 0 0 20px rgba(255, 159, 28, 0.3);
        }}
        </style>
        <div class="crypto-bot-header">
            <img src='data:image/png;base64,{img_base64}' width="140" class="crypto-bot-avatar" alt="Cripto Bolt" />
        </div>
        """, unsafe_allow_html=True
    )

    # Extrai o primeiro nome do usuário logado
    _user_data = st.session_state.get('user')
    _primeiro_nome = ''
    if _user_data and isinstance(_user_data, dict):
        _nome_completo = _user_data.get('nome', '')
        _primeiro_nome = _nome_completo.strip().split(
        )[0].capitalize() if _nome_completo.strip() else ''

    # Instancia o system_prompt no início do escopo da função
    _nome_instrucao = (
        f"O nome do usuário é {_primeiro_nome}. "
        f"Use o nome dele na primeira mensagem e depois repita-o de forma natural a cada 4 ou 5 respostas para manter um tom amigável. "
        f"Nunca force ou repita o nome em toda resposta.\n"
    ) if _primeiro_nome else ""

    system_prompt = _nome_instrucao + """
Você é o Cripto Bolt, um analista sênior de criptoativos especializado em protocolos DeFi, tokens, pools de liquidez e estratégias de Day Trade.

Responda sempre de forma clara, objetiva, profissional e educacional, ajudando o usuário a entender protocolos, ativos, pools e estratégias. Nunca prometa lucros, não invente dados e não crie garantias de assertividade.

REGRAS ESSENCIAIS:
- Responda apenas ao que foi perguntado, sem fugir do contexto.
- Use linguagem simples, mas técnica.
- Nunca deixe a resposta incompleta.
- Sempre destaque riscos ao falar de futuros, alavancagem, pools ou ativos voláteis.
- Não use frases como "lucro garantido", "esse ativo vai subir" ou "essa estratégia tem 90% de assertividade". Prefira: "Historicamente, esse setup pode funcionar melhor em certas condições, mas envolve risco e depende de execução."

FONTES DE REFERÊNCIA:
- Considere informações de fontes como DeFiLlama (protocolos DeFi), CoinMarketCap (tokens e contexto de mercado), Binance Academy (estratégias de Day Trade) e CoinMarketCap Academy (educação cripto).

COMO RESPONDER:
- Seja CONCISO. Máximo 3 parágrafos curtos por resposta, sem listas longas nem subtítulos.
- Nunca repita informações que já aparecem em cards/tabelas visuais exibidos acima da sua resposta.
- Cada parágrafo deve trazer uma informação nova. Não reescreva a mesma ideia com palavras diferentes.
- Evite introduções genéricas e conclusões vazias. Vá direto para tese, risco e uso prático.
- Para perguntas sobre investimento, foque em: tese principal, principal risco e aplicabilidade prática — em no máximo 3 frases cada.
- Para Day Trade, mostre: entrada, stop loss e gestão de risco — de forma direta e sem rodeios.
- Para pools de liquidez, destaque: risco de impermanent loss e perfil de risco em 2-3 frases.
- Para cálculo de Impermanent Loss: se o usuário informar preço de entrada, preço atual e capital, calcule diretamente e exiba o card — não peça confirmação.
- Para Range Optimizer no Uniswap V3: se o usuário mencionar um token, sugira a faixa ideal com base na volatilidade 7d.
- Para análise interativa avançada (calculadora IL com formulário, ranking filtrado por chain, stablecoins detalhadas), indique o menu "💧 DeFi & Pools" no painel lateral.

OUTRAS REGRAS:
- Só apresente o link de assinatura se o usuário demonstrar forte interesse comercial: https://buy.stripe.com/test_7sI17R3wleKMctqaEJ
- Se o usuário pedir contato do programador, envie: https://wa.me/5531998417976
- Seja sempre objetivo, técnico e confiável. Priorize análise prática e evite frases promocionais ou exageros.
- Foque em ajudar o usuário a tomar decisões mais conscientes.
"""

    def _resposta_cadastro_agendamento(prompt: str) -> str | None:
        if not (is_health_question(prompt) or is_schedule_meeting_question(prompt)):
            return None

        user_data = st.session_state.get('user') or {}
        if user_data and not bool(user_data.get('is_verified', True)):
            return 'Estou aguardando a finalização do seu cadastro para continuar.'
        return 'Estou aguardando o preenchimento completo do formulário para continuar.'

    def _compact_assistant_text(text: str) -> str:
        if not text:
            return text

        normalized = text.replace('\r\n', '\n').strip()
        blocks = [block.strip() for block in re.split(
            r'\n\s*\n', normalized) if block.strip()]
        compacted = []
        seen = set()

        for block in blocks:
            key = re.sub(r'\s+', ' ', block).strip().lower()
            if key in seen:
                continue
            seen.add(key)
            compacted.append(block)

        return '\n\n'.join(compacted)

    # Função para verificar se a pergunta está relacionada a cadastro
    def is_health_question(prompt):
        keywords = ["cadastrar", "inscrição", "quero me cadastrar", "gostaria de me registrar",
                    "desejo me cadastrar", "quero fazer o cadastro", "quero me registrar", "quero me increver",
                    "desejo me registrar", "desejo me inscrever", "eu quero me cadastrar", "eu desejo me cadastrar",
                    "eu desejo me registrar", "eu desejo me inscrever", "eu quero me registrar", "eu desejo me registrar",
                    "eu quero me inscrever"]
        return any(keyword.lower() in prompt.lower() for keyword in keywords)

    # Função que analisa desejo de agendar uma reunião
    def is_schedule_meeting_question(prompt):
        keywords = [
            "agendar reunião", "quero agendar uma reunião", "gostaria de agendar uma reunião",
            "desejo agendar uma reunião", "quero marcar uma reunião", "gostaria de marcar uma reunião",
            "desejo marcar uma reunião", "posso agendar uma reunião", "posso marcar uma reunião",
            "Eu gostaria de agendar uma reuniao", "eu quero agendar", "eu quero agendar uma reunião,",
            "quero reunião"
        ]
        return any(keyword.lower() in prompt.lower() for keyword in keywords)

    # Ícones do chat
    default_image_path = './src/img/usuario-crypto.png'
    icons = {'assistant': './src/img/cripto-bolt.png',
             'user': default_image_path}

    # Dialog de instruções
    @st.dialog("📖 Como Interagir com o Cripto Bolt", width="large")
    def show_instructions_dialog():
        st.markdown("""
        <style>
        .dialog-content {{
            border: 2px solid rgba(23, 190, 187, 0.4);
            border-radius: 18px;
            padding: 1.5rem;
            background: rgba(15, 23, 42, 0.3);
            box-shadow: 0 8px 24px rgba(23, 190, 187, 0.1);
        }}
        .instruction-item {{
            border-left: 4px solid rgba(23, 190, 187, 0.6);
            padding-left: 1rem;
            margin-bottom: 1rem;
            background: rgba(255, 255, 255, 0.02);
            padding: 0.8rem;
            border-radius: 8px;
        }}
        .instruction-title {{
            font-weight: 700;
            color: #17bebb;
            font-size: 1.05rem;
            margin-bottom: 0.3rem;
        }}
        .instruction-desc {{
            color: #94a3b8;
            font-size: 0.95rem;
            line-height: 1.5;
        }}
        </style>
        
        <div class="dialog-content">
            <h3 style="color: #17bebb; margin-bottom: 1.5rem;">🎯 Dicas de Interação com o Cripto Bolt</h3>
            
            <div class="instruction-item">
                <div class="instruction-title">1️⃣ Inicie com uma Saudação</div>
                <div class="instruction-desc">Comece a conversa de forma amigável para criar um bom contexto.</div>
            </div>
            
            <div class="instruction-item">
                <div class="instruction-title">2️⃣ Informe seu Nível de Experiência</div>
                <div class="instruction-desc">Diga se você é novato ou veterano no mercado de criptomoedas para que eu adeque as explicações.</div>
            </div>
            
            <div class="instruction-item">
                <div class="instruction-title">3️⃣ Faça Perguntas Claras e Específicas</div>
                <div class="instruction-desc">Quanto mais detalhado for sua pergunta, melhor será a análise. Exemplo: "Qual é a tese de investimento do Ethereum?"</div>
            </div>
            
            <div class="instruction-item">
                <div class="instruction-title">4️⃣ Solicite Análises de Mercado</div>
                <div class="instruction-desc">Peça cotações, análises técnicas, sentimento de mercado ou previsões de movimentos de ativos.</div>
            </div>
            
            <div class="instruction-item">
                <div class="instruction-title">5️⃣ Explore DeFi e Pools de Liquidez</div>
                <div class="instruction-desc">Pergunte sobre protocolos, pools de liquidez, impermanent loss e estratégias de yield farming.</div>
            </div>
            
            <div class="instruction-item">
                <div class="instruction-title">6️⃣ Aprenda sobre Estratégias de Day Trade</div>
                <div class="instruction-desc">Solicite setups de entrada, gestão de risco, stop loss e análises técnicas para operações intradiárias.</div>
            </div>
            
            <div class="instruction-item">
                <div class="instruction-title">7️⃣ Solicite Ações Específicas</div>
                <div class="instruction-desc">Você pode pedir para agendar uma reunião, enviar análises por e-mail ou receber relatórios completos.</div>
            </div>
            
            <div class="instruction-item">
                <div class="instruction-title">8️⃣ Dê Feedback e Melhore as Respostas</div>
                <div class="instruction-desc">Sempre que precisar de mais detalhes ou de uma abordagem diferente, me avise!</div>
            </div>
            
            <hr style="border: 1px solid rgba(23, 190, 187, 0.2); margin: 1.5rem 0;">
            
            <div style="background: rgba(23, 190, 187, 0.1); padding: 1rem; border-radius: 12px; border-left: 4px solid #17bebb;">
                <p style="color: #17bebb; font-weight: 700; margin-bottom: 0.5rem;">💡 Dica Extra:</p>
                <p style="color: #94a3b8; margin: 0;">Quanto mais específica sua pergunta, melhor é a análise. Inclua contextos como: "Sou novato", "Tenho $1000", "Quero fazer Day Trade" ou "Estou interessado em yield farming".</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Sidebar: instruções e ações do bot
    with st.sidebar:
        col1, col2 = st.columns(2)
        with col1:
            if st.button('📖 Instruções', use_container_width=True):
                show_instructions_dialog()
        with col2:
            if st.button('❓ Ajuda', use_container_width=True):
                st.info("**Precisa de ajuda?**\n\nClique em '📖 Instruções' para ver como interagir melhor com o Cripto Bolt, ou formule sua pergunta no chat!")
        
        st.divider()
        
        st.info("""
        **Bem-vindo ao Cripto Bolt!**

        Sou seu assistente de análise de criptoativos, DeFi e Day Trade. Faça perguntas sobre:
        - 💰 Cotações e análise de mercado
        - 📊 Análise técnica e sentimento
        - 🔄 Protocolos DeFi e pools
        - 📈 Estratégias de investimento
        - 🚀 Oportunidades de yield farming
        """)
        st.info("""
        **Instruções para Interação com o CRYPTO BOT**

        1. **Inicie a conversa** com uma saudação amigável.
        2. **Informe seu nível de experiência**: novato ou veterano no mercado de criptomoedas.
        3. **Formule perguntas claras** sobre tópicos específicos, como investimentos e tecnologia blockchain.
        4. **Peça previsões de mercado** e movimentos de criptomoedas.
        5. **Agende uma consultoria** mencionando seu interesse.
        6. **Pergunte sobre o curso Águia Crypto** para saber mais sobre o conteúdo e inscrição.
        7. **Dê feedback** sobre as respostas recebidas para melhorar a interação.
        8. **Agradeça ao CRYPTO BOT** ao final da conversa.
        """)

        st.sidebar.markdown('---')

    # Resolve o avatar do usuário: imagem de perfil ou padrão
    user_profile_img = st.session_state.get('image')
    if user_profile_img and os.path.exists(user_profile_img):
        user_avatar = user_profile_img
    else:
        user_avatar = default_image_path

    icons['user'] = user_avatar

    # Store LLM-generated responses
    if 'messages' not in st.session_state:
        import datetime
        _hora = datetime.datetime.now().hour
        _saudacao = 'Bom dia' if _hora < 12 else (
            'Boa tarde' if _hora < 18 else 'Boa noite')
        _greeting_nome = f' {_primeiro_nome}' if _primeiro_nome else ''
        st.session_state.messages = [
            {'role': 'assistant', 'content': f'{_saudacao}{_greeting_nome}! Sou o Cripto Bolt, seu analista de criptoativos. Estou aqui para ajudar com criptomoedas, protocolos DeFi, tokens, pools de liquidez ou estratégias de Day Trade. O que você gostaria de saber hoje?'}]

    # Display or clear chat messages
    for message in st.session_state.messages:
        with st.chat_message(message['role'], avatar=icons[message['role']]):
            st.markdown(message['content'], unsafe_allow_html=True)

    def clear_chat_history():
        st.session_state.messages = [
            {'role': 'assistant', 'content': 'Olá! Sou o CRYPTO BOT, seu guia no mercado de criptomoedas, pronto para te ajudar a prever movimentos e otimizar seus investimentos. Vamos juntos transformar seu conhecimento em resultados!'}]

    def sair():
        st.session_state.clear()
        st.session_state.page = 'home'

    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.button('LIMPAR CONVERSA', on_click=clear_chat_history,
                  use_container_width=True)
    with col2:
        st.button('SAIR', on_click=sair, use_container_width=True)

    st.sidebar.markdown(
        'Desenvolvido por [WILLIAM EUSTÁQUIO](https://www.instagram.com/flashdigital.tech/)')

    def generate_groq_response(cmc_context: str | None = None, has_card: bool = False):
        history = []
        for dict_message in st.session_state.messages:
            if dict_message['role'] == 'user':
                history.append(
                    {'role': 'user', 'content': dict_message['content']})
            else:
                history.append(
                    {'role': 'assistant', 'content': dict_message['content']})

        prompt = [{'role': 'system', 'content': system_prompt}]
        if cmc_context:
            prompt.append({'role': 'system', 'content': cmc_context})
        if has_card:
            prompt.append({'role': 'system', 'content': 'Os dados já estão exibidos visualmente acima. Escreva APENAS 2-3 parágrafos curtos de comentário analítico. Não repita números, não use listas, não use subtítulos, não repita a mesma conclusão em dois parágrafos.'})
        prompt.extend(history[-10:])

        api_key = _get_groq_api_key()
        if api_key:
            try:
                client = groq.Groq(api_key=api_key)
                response = client.chat.completions.create(
                    model='llama-3.3-70b-versatile',
                    messages=prompt,
                    max_tokens=400 if has_card else 800,
                    temperature=0.1,
                    stream=True,
                )
                for chunk in response:
                    if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            except Exception as e:
                yield f'Erro ao acessar o LLM: {e}'
        else:
            yield 'Desculpe, o assistente automático está temporariamente indisponível. Por favor, tente novamente mais tarde ou entre em contato com o suporte.'

    # ─── Detecção e correção de saudação por horário ──────────────────────────
    def _saudacao_correta() -> tuple[str, str]:
        """Retorna (saudacao, descricao_faixa) baseado na hora atual."""
        import datetime
        hora = datetime.datetime.now().hour
        minuto = datetime.datetime.now().minute
        total_min = hora * 60 + minuto
        if total_min < 720:           # 00:00 – 11:59
            return "Bom dia", "ainda não são 12:00"
        elif total_min <= 1110:       # 12:00 – 18:30
            return "Boa tarde", "já são mais de 12:00"
        else:                         # 18:31 – 23:59
            return "Boa noite", "já são mais de 18:30"

    def _detectar_saudacao_usuario(texto: str) -> str | None:
        """Retorna a saudação detectada no texto do usuário, ou None."""
        t = texto.lower().strip()
        if re.search(r'\bbom\s+dia\b', t):
            return "bom dia"
        if re.search(r'\bboa\s+tarde\b', t):
            return "boa tarde"
        if re.search(r'\bboa\s+noite\b', t):
            return "boa noite"
        return None

    _SAUDACAO_MAP = {
        "bom dia":   "Bom dia",
        "boa tarde": "Boa tarde",
        "boa noite": "Boa noite",
    }

    def _resposta_correcao_saudacao(saudacao_usuario: str, nome: str) -> str | None:
        """Retorna mensagem de correção se a saudação estiver errada, ou None se correta."""
        correta, motivo = _saudacao_correta()
        usada = _SAUDACAO_MAP.get(saudacao_usuario, "")
        if usada == correta:
            return None  # saudação correta, sem correção
        nome_parte = f" {nome}" if nome else ""
        # Monta a correção personalizada
        if correta == "Bom dia":
            return f"Bom dia{nome_parte}! {motivo.capitalize()} 😊 Como posso te ajudar?"
        elif correta == "Boa tarde":
            return f"Boa tarde{nome_parte}! {motivo.capitalize()} 😊 Como posso te ajudar?"
        else:
            return f"Boa noite{nome_parte}! {motivo.capitalize()} 😊 Como posso te ajudar?"

    # User-provided prompt
    if prompt := st.chat_input():
        st.session_state.messages.append({'role': 'user', 'content': prompt})

        with st.chat_message(name='user', avatar=user_avatar):
            st.write(prompt)

    # Generate a new response if the last message is not from assistant
    if st.session_state.messages and st.session_state.messages[-1]['role'] != 'assistant':
        user_prompt = st.session_state.messages[-1]['content']
        user_prompt_lower = user_prompt.lower()

        resposta_fluxo_cadastro = _resposta_cadastro_agendamento(user_prompt)
        if resposta_fluxo_cadastro:
            with st.chat_message(name='assistant', avatar='./src/img/cripto-bolt.png'):
                st.markdown(resposta_fluxo_cadastro)
            st.session_state.messages.append(
                {'role': 'assistant', 'content': resposta_fluxo_cadastro})
            st.stop()

        # ── Verificação de saudação por horário ──────────────────────────────
        _saudacao_detectada = _detectar_saudacao_usuario(user_prompt)
        if _saudacao_detectada:
            _correcao = _resposta_correcao_saudacao(
                _saudacao_detectada, _primeiro_nome)
            if _correcao:
                with st.chat_message(name='assistant', avatar='./src/img/cripto-bolt.png'):
                    st.markdown(_correcao)
                st.session_state.messages.append(
                    {'role': 'assistant', 'content': _correcao})
                st.stop()
        # ─────────────────────────────────────────────────────────────────────

        if 'protocolo defi' in user_prompt_lower or 'protocolos defi' in user_prompt_lower:
            protocolos = buscar_protocolos_defi()
            resposta = 'Protocolos DeFi populares: ' + ', '.join(protocolos)
            with st.chat_message(name='assistant', avatar='./src/img/cripto-bolt.png'):
                st.write(resposta)
            message = {'role': 'assistant', 'content': resposta}
            st.session_state.messages.append(message)
        else:
            html_card = None
            context = None
            email_payload = None
            stablecoins_query = _detectar_intencao_stablecoins(user_prompt)
            analyst_protocol = _detectar_intencao_analise_protocolo(user_prompt)
            analyst_pool = None if analyst_protocol else _detectar_intencao_analise_pool(user_prompt)
            analyst_symbol = None if (analyst_protocol or analyst_pool) else _detectar_intencao_analise_token(user_prompt)
            pedir_email = _usuario_pediu_envio_email(user_prompt)

            # --- CoinMarketCap ---
            # Prioridade 1: stablecoins
            if stablecoins_query:
                with st.spinner('Buscando dados de stablecoins...'):
                    result = _formatar_stablecoins_defi()
                    if result:
                        html_card, context = result
            else:
                if analyst_protocol:
                    with st.spinner(f'Gerando leitura de protocolo para {analyst_protocol}...'):
                        result = _formatar_relatorio_perplexity_protocolo(analyst_protocol)
                        if result:
                            html_card, context = result
                            email_payload = {
                                'tipo_relatorio': 'protocolo',
                                'titulo': f'Relatório de protocolo {analyst_protocol}',
                                'metricas': _coletar_contexto_protocolo(analyst_protocol),
                            }
                elif analyst_pool:
                    with st.spinner(f'Gerando leitura de pool para {analyst_pool}...'):
                        result = _formatar_relatorio_perplexity_pool(analyst_pool)
                        if result:
                            html_card, context = result
                            email_payload = {
                                'tipo_relatorio': 'pool',
                                'titulo': f'Relatório de pool {analyst_pool}',
                                'metricas': _coletar_contexto_pool(analyst_pool),
                            }
                elif analyst_symbol:
                    with st.spinner(f'Gerando relatório de inteligência para {analyst_symbol}...'):
                        result = _formatar_relatorio_perplexity(analyst_symbol)
                        if result:
                            html_card, context = result
                            email_payload = {
                                'tipo_relatorio': 'token',
                                'titulo': f'Relatório de {analyst_symbol}',
                                'metricas': _coletar_contexto_token(analyst_symbol),
                            }

                # Prioridade 2: ranking do mercado
                limit = _detectar_intencao_ranking(user_prompt) if not html_card else None
                if limit:
                    with st.spinner(f'Buscando top {limit} criptomoedas em tempo real...'):
                        result = _formatar_ranking_cmc(limit)
                        if result:
                            html_card, context = result
                            email_payload = {
                                'tipo_relatorio': 'pesquisa',
                                'titulo': f'Pesquisa de mercado - Top {limit} criptomoedas',
                                'metricas': {'Escopo': f'Top {limit} criptomoedas'},
                            }
                else:
                    # Prioridade 2: cotação em tempo real
                    simbolo = _detectar_simbolo_cotacao(user_prompt) if not html_card else None
                    if simbolo:
                        with st.spinner(f'Buscando cotação de {simbolo} em tempo real...'):
                            result = _formatar_cotacao_cmc(simbolo)
                            if result:
                                html_card, context = result
                                email_payload = {
                                    'tipo_relatorio': 'pesquisa',
                                    'titulo': f'Cotação e contexto de {simbolo}',
                                    'metricas': _coletar_contexto_token(simbolo),
                                }
                    else:
                        # Prioridade 3: metadados do token
                        simbolo_meta = _detectar_simbolo_metadata(user_prompt) if not html_card else None
                        if simbolo_meta:
                            with st.spinner(f'Buscando informações de {simbolo_meta}...'):
                                result = _formatar_metadata_cmc(simbolo_meta)
                                if result:
                                    html_card, context = result
                                    email_payload = {
                                        'tipo_relatorio': 'pesquisa',
                                        'titulo': f'Pesquisa sobre {simbolo_meta}',
                                        'metricas': _coletar_contexto_token(simbolo_meta),
                                    }

            # --- DeFiLlama (se CMC não respondeu) ---
            if not html_card:
                # Prioridade 4: TVL de protocolo DeFi
                slug_protocolo = _detectar_protocolo_defi(user_prompt)
                if slug_protocolo:
                    with st.spinner(f'Buscando TVL do protocolo {slug_protocolo}...'):
                        result = _formatar_tvl_protocolo(slug_protocolo)
                        if result:
                            html_card, context = result
                            email_payload = email_payload or {
                                'tipo_relatorio': 'protocolo',
                                'titulo': f'TVL do protocolo {slug_protocolo}',
                                'metricas': _coletar_contexto_protocolo(slug_protocolo),
                            }
                else:
                    # Prioridade 5: TVL de blockchain
                    chain = _detectar_chain_defi(user_prompt)
                    if chain:
                        with st.spinner(f'Buscando TVL da chain {chain}...'):
                            result = _formatar_tvl_chain(chain)
                            if result:
                                html_card, context = result
                                email_payload = email_payload or {
                                    'tipo_relatorio': 'pesquisa',
                                    'titulo': f'TVL da chain {chain}',
                                    'metricas': {'Chain': chain},
                                }
                    else:
                        # Prioridade 6: stablecoins ja tratada acima
                        if stablecoins_query:
                            pass
                        else:
                            # Prioridade 7: análise de pools LP
                            lp_query = _detectar_intencao_lp(user_prompt)
                            if lp_query:
                                with st.spinner('Analisando pools de liquidez...'):
                                    result = _formatar_lp_analise(lp_query)
                                    if result:
                                        html_card, context = result
                                        email_payload = email_payload or {
                                            'tipo_relatorio': 'pool',
                                            'titulo': f'Análise de pool {lp_query}',
                                            'metricas': _coletar_contexto_pool(lp_query),
                                        }
                            else:
                                # Prioridade 8: calculadora de Impermanent Loss
                                il_params = _detectar_intencao_il_calc(
                                    user_prompt)
                                if il_params:
                                    entrada, atual, capital = il_params
                                    result = _formatar_il_calc(
                                        entrada, atual, capital)
                                    if result:
                                        html_card, context = result
                                        email_payload = {
                                            'tipo_relatorio': 'pesquisa',
                                            'titulo': 'Cálculo de impermanent loss',
                                            'metricas': {'Preço de entrada': entrada, 'Preço atual': atual, 'Capital': capital},
                                        }
                                else:
                                    # Prioridade 9: range optimizer Uniswap V3
                                    range_sym = _detectar_intencao_range_opt(
                                        user_prompt)
                                    if range_sym:
                                        with st.spinner(f'Calculando range ideal para {range_sym}...'):
                                            result = _formatar_range_opt(
                                                range_sym)
                                            if result:
                                                html_card, context = result
                                                email_payload = {
                                                    'tipo_relatorio': 'pesquisa',
                                                    'titulo': f'Range optimizer {range_sym}',
                                                    'metricas': _coletar_contexto_token(range_sym),
                                                }

            with st.chat_message(name='assistant', avatar='./src/img/cripto-bolt.png'):
                if html_card:
                    st.markdown(html_card, unsafe_allow_html=True)
                response = generate_groq_response(
                    cmc_context=context, has_card=bool(html_card))
                full_response = st.write_stream(response)
            full_response = _compact_assistant_text(full_response or "")
            saved = (html_card if html_card else "") + \
                ("\n\n" + full_response if full_response else "")
            message = {'role': 'assistant', 'content': saved}
            st.session_state.messages.append(message)

            if pedir_email and email_payload:
                user_email = (st.session_state.get('user') or {}).get('email')
                user_name = (st.session_state.get('user') or {}).get('nome', '')
                if user_email:
                    try:
                        metricas = {}
                        for key, value in (email_payload.get('metricas') or {}).items():
                            if value in (None, '', [], {}):
                                continue
                            label = str(key).replace('_', ' ').title()
                            metricas[label] = value
                            if len(metricas) >= 6:
                                break
                        Notificador().enviar_relatorio_chat(
                            user_email,
                            nome=user_name,
                            tipo_relatorio=email_payload['tipo_relatorio'],
                            titulo=email_payload['titulo'],
                            resumo=full_response or 'Relatório solicitado no chat.',
                            metricas=metricas,
                            insights=['Revisar risco, liquidez e contexto antes de executar qualquer operação.'],
                        )
                        email_msg = f'Relatório enviado para {user_email}.'
                    except Exception as exc:
                        email_msg = f'Não foi possível enviar o relatório por e-mail: {exc}'
                else:
                    email_msg = 'Não encontrei um e-mail cadastrado no seu perfil para enviar o relatório.'

                with st.chat_message(name='assistant', avatar='./src/img/cripto-bolt.png'):
                    st.markdown(email_msg)
                st.session_state.messages.append({'role': 'assistant', 'content': email_msg})
