import re

import streamlit as st

from apis_cripto import CoinMarketCapAPI, DefiLlamaAPI

# ─── CSS compartilhado ────────────────────────────────────────────────────────
_CSS = (
    "<style>"
    ".cb{background:rgba(255,255,255,.86);"
    "border:1px solid rgba(12,123,179,.14);border-left:4px solid #17bebb;"
    "border-radius:22px;padding:18px 22px;margin:8px 0;"
    "box-shadow:0 18px 44px rgba(19,62,107,.10);backdrop-filter:blur(12px);"
    "font-family:'Manrope',Arial,sans-serif;color:#10233a;}"
    ".cb-hdr{display:flex;align-items:center;gap:8px;padding-bottom:10px;"
    "margin-bottom:12px;border-bottom:1px solid rgba(12,123,179,.12);}"
    ".cb-sym{color:#0c7bb3;font-size:1.05rem;font-weight:800;}"
    ".cb-name{color:#5f738b;font-size:.82rem;}"
    ".cb-badge{margin-left:auto;background:linear-gradient(135deg,#0c7bb3,#17bebb);color:#fff;font-size:.68rem;"
    "padding:3px 9px;border-radius:20px;font-weight:700;white-space:nowrap;}"
    ".cb-lbl{color:#5f738b;font-size:.68rem;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:3px;}"
    ".cb-big{color:#10233a;font-size:1.85rem;font-weight:800;letter-spacing:-.5px;margin-bottom:14px;}"
    ".cb-g3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;}"
    ".cb-g2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;}"
    ".cb-cell{background:rgba(247,251,255,.92);border:1px solid rgba(12,123,179,.10);border-radius:16px;padding:10px 9px;text-align:center;}"
    ".cb-clbl{color:#5f738b;font-size:.67rem;margin-bottom:4px;}"
    ".cb-cval{font-size:.92rem;font-weight:600;}"
    ".up{color:#4caf50;}.dn{color:#ef5350;}"
    ".cb-foot{margin-top:10px;text-align:right;color:#5f738b;font-size:.63rem;}"
    ".cb-tbl{width:100%;border-collapse:collapse;font-size:.8rem;}"
    ".cb-tbl th{color:#0c7bb3;font-size:.67rem;text-transform:uppercase;letter-spacing:.8px;"
    "padding:5px 8px;border-bottom:1px solid rgba(12,123,179,.16);text-align:left;}"
    ".cb-tbl td{padding:7px 8px;border-bottom:1px solid rgba(12,123,179,.06);vertical-align:middle;}"
    ".cb-tbl tr:last-child td{border-bottom:none;}"
    ".cb-desc{font-size:.8rem;color:#5f738b;line-height:1.5;margin-top:8px;"
    "border-top:1px solid rgba(12,123,179,.10);padding-top:8px;}"
    ".defi-hero{margin-bottom:1rem;padding:1.1rem 1.3rem;border-radius:24px;"
    "background:rgba(255,255,255,.82);border:1px solid rgba(12,123,179,.14);"
    "box-shadow:0 18px 44px rgba(19,62,107,.10);backdrop-filter:blur(12px);}"
    ".defi-title{margin:0;color:#10233a;font-family:'Space Grotesk',sans-serif;font-size:1.9rem;font-weight:800;}"
    ".defi-copy{margin:6px 0 0 0;color:#5f738b;font-size:.98rem;}"
    "</style>"
)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _fmt_usd(v: float) -> str:
    if v >= 1e12: return f"US$ {v / 1e12:.2f}T"
    if v >= 1e9:  return f"US$ {v / 1e9:.2f}B"
    if v >= 1e6:  return f"US$ {v / 1e6:.2f}M"
    if v >= 1e3:  return f"US$ {v / 1e3:.2f}K"
    return f"US$ {v:,.4f}"


def _vc(v: float) -> str:
    return "up" if v >= 0 else "dn"


def _va(v: float) -> str:
    return "▲" if v >= 0 else "▼"


# ─── Cálculos LP ─────────────────────────────────────────────────────────────
def _calcular_il(preco_entrada: float, preco_atual: float) -> float:
    """Impermanent Loss % — fórmula fechada Uniswap V2."""
    if preco_entrada <= 0 or preco_atual <= 0:
        return 0.0
    r = preco_atual / preco_entrada
    return ((2 * r ** 0.5 / (1 + r)) - 1) * 100


def _range_sugerido(vol_7d_pct: float) -> tuple[str, str, str]:
    """(faixa, descrição, cor) por nível de volatilidade."""
    if vol_7d_pct < 5:
        return "Estreita (+/-5%)", "Regime lateral - concentre para maximizar fees", "#4caf50"
    elif vol_7d_pct < 15:
        return "Media (+/-15%)", "Volatilidade moderada - equilibrio eficiencia/cobertura", "#ff9800"
    else:
        return "Larga (+/-30%+)", "Alta volatilidade - faixa ampla reduz risco de sair do range", "#ef5350"


def _score_pool(volume_24h: float, tvl: float, apy_base: float, il_7d: float) -> float:
    """Score LP 0–100."""
    if tvl <= 0:
        return 0.0
    vol_ratio = min(volume_24h / tvl, 1.0)
    apy_norm  = min(apy_base / 200, 1.0)
    il_pen    = min(abs(il_7d or 0) / 20, 1.0)
    return round(max(0.0, min(100.0, (0.50 * vol_ratio + 0.35 * apy_norm - 0.15 * il_pen) * 100)), 1)


# ─── Pares populares por categoria ───────────────────────────────────────────
_PARES_POPULARES = {
    "⚡ Blue Chips": [
        "ETH/USDC", "ETH/USDT", "WBTC/USDC", "WBTC/USDT",
        "ETH/WBTC", "BNB/USDC", "BNB/USDT",
    ],
    "🔵 Layer 2 & Ecosystem": [
        "ARB/USDC", "ARB/ETH", "OP/USDC", "OP/ETH",
        "MATIC/USDC", "MATIC/ETH", "AVAX/USDC", "AVAX/USDT",
    ],
    "🟣 DeFi Tokens": [
        "UNI/USDC", "UNI/ETH", "AAVE/USDC", "AAVE/ETH",
        "LINK/USDC", "LINK/ETH", "CRV/USDC", "LDO/USDC",
    ],
    "🌐 Outras Redes": [
        "SOL/USDC", "SOL/USDT", "XRP/USDC", "ADA/USDC",
        "DOT/USDC", "NEAR/USDC", "ATOM/USDC",
    ],
}
_TODOS_PARES = ["🔍 Top Geral (sem filtro)"] + [p for pares in _PARES_POPULARES.values() for p in pares]


# ─── Tab 1: Ranking de Pools ─────────────────────────────────────────────────
def _tab_ranking():
    st.markdown("### 🏆 Ranking de Pools de Liquidez")
    st.caption("Pools ranqueadas pelo Score LP = 0.50×(Vol/TVL) + 0.35×APY_base − 0.15×|IL_7d|")

    # ── Seleção rápida de par ─────────────────────────────────────────────────
    col_sel, col_man = st.columns([3, 2])
    with col_sel:
        par_selecionado = st.selectbox(
            "Par de tokens — seleção rápida",
            _TODOS_PARES,
            index=0,
            help="30 pares populares pré-listados. Use 'Inserir manualmente' para outros.",
        )
    with col_man:
        par_manual = st.text_input(
            "Ou digite outro par",
            placeholder="ex: PEPE/ETH, cbBTC/USDC",
            help="Sobrescreve a seleção rápida se preenchido.",
        ).strip().upper()

    # Manual tem prioridade; seleção rápida "Top Geral" vira string vazia
    if par_manual:
        par_input = par_manual
    elif par_selecionado == "🔍 Top Geral (sem filtro)":
        par_input = ""
    else:
        par_input = par_selecionado.replace("/", "/")  # normaliza

    # ── Legenda por categoria ─────────────────────────────────────────────────
    with st.expander("📂 Ver pares por categoria", expanded=False):
        cols = st.columns(len(_PARES_POPULARES))
        for col, (categoria, pares) in zip(cols, _PARES_POPULARES.items()):
            with col:
                st.markdown(f"**{categoria}**")
                for p in pares:
                    st.caption(p)

    col2, col3 = st.columns([3, 1])
    with col2:
        chain_filter = st.selectbox(
            "Chain",
            ["Todas", "Ethereum", "Arbitrum", "Base", "Optimism", "Polygon", "BSC", "Avalanche"],
        )
    with col3:
        top_n = st.selectbox("Top", [5, 10, 20], index=0)

    if st.button("🔍 Buscar Pools", use_container_width=True, type="primary"):
        with st.spinner("Buscando pools na DeFiLlama..."):
            try:
                llama = DefiLlamaAPI()
                data = llama.yields_pools_public()
                pools_raw = data.get("data", []) if isinstance(data, dict) else []

                # Filtro por par
                if par_input:
                    tokens = [t.strip() for t in re.split(r"[/\-]", par_input)]
                    filtered = [
                        p for p in pools_raw
                        if all(t in (p.get("symbol") or "").upper() for t in tokens)
                        and (p.get("tvlUsd") or 0) > 50_000
                    ]
                else:
                    filtered = [
                        p for p in pools_raw
                        if (p.get("tvlUsd") or 0) > 500_000
                        and (p.get("volumeUsd1d") or 0) > 0
                        and (p.get("apyBase") or 0) > 0
                    ]

                # Filtro por chain
                if chain_filter != "Todas":
                    filtered = [
                        p for p in filtered
                        if (p.get("chain") or "").lower() == chain_filter.lower()
                    ]

                if not filtered:
                    st.warning("Nenhuma pool encontrada com esses filtros.")
                    return

                # Ranqueia
                scored = sorted(
                    filtered,
                    key=lambda p: _score_pool(
                        p.get("volumeUsd1d") or 0,
                        p.get("tvlUsd") or 1,
                        p.get("apyBase") or 0,
                        p.get("il7d") or 0,
                    ),
                    reverse=True,
                )[:top_n]

                # Salva no session_state para a Calculadora de IL usar
                st.session_state["defi_ranking_pools"] = scored
                st.session_state["defi_ranking_par"] = par_input or "Top Geral"

                # Monta card HTML
                def _bar(s):
                    cor = "#4caf50" if s >= 60 else ("#ff9800" if s >= 35 else "#ef5350")
                    return (
                        f'<div style="background:rgba(12,123,179,.10);border-radius:999px;height:6px;width:100%;margin-top:4px">'
                        f'<div style="background:{cor};width:{s}%;height:6px;border-radius:4px"></div></div>'
                    )

                medals = ["🥇", "🥈", "🥉"] + [f"{i+1}️⃣" for i in range(3, top_n)]
                rows = ""
                for i, p in enumerate(scored):
                    sym      = p.get("symbol", "")
                    project  = p.get("project", "")
                    chain    = p.get("chain", "")
                    tvl      = p.get("tvlUsd", 0) or 0
                    apy_base = p.get("apyBase", 0) or 0
                    apy_rwd  = p.get("apyReward", 0) or 0
                    il_7d    = p.get("il7d", 0) or 0
                    vol_24h  = p.get("volumeUsd1d", 0) or 0
                    score    = _score_pool(vol_24h, tvl, apy_base, il_7d)
                    il_cls   = "dn" if il_7d < -1 else ("up" if il_7d > 0 else "")
                    medal    = medals[i] if i < len(medals) else f"#{i+1}"
                    rows += (
                        f'<tr>'
                        f'<td style="font-size:.8rem">{medal} <b>{sym}</b>'
                        f'<br><span style="color:#5f738b;font-size:.7rem">{project} · {chain}</span></td>'
                        f'<td style="text-align:center">'
                        f'<span style="font-weight:700;color:#0c7bb3">{score}</span>{_bar(score)}</td>'
                        f'<td style="text-align:right">'
                        f'<span style="color:#4caf50;font-weight:600">{apy_base:.1f}%</span>'
                        f'<br><span style="color:#5f738b;font-size:.7rem">+{apy_rwd:.1f}% reward</span></td>'
                        f'<td style="text-align:right">{_fmt_usd(tvl)}</td>'
                        f'<td style="text-align:right;font-size:.8rem">{_fmt_usd(vol_24h)}</td>'
                        f'<td class="{il_cls}" style="text-align:right;font-size:.8rem">{il_7d:+.2f}%</td>'
                        f'</tr>'
                    )

                # Faixa recomendada pela melhor pool
                best = scored[0]
                b_il = abs(best.get("il7d", 0) or 0)
                b_range, b_range_desc, b_cor = _range_sugerido(b_il * 52)
                b_vol = best.get("volumeUsd1d", 0) or 0
                b_tvl = best.get("tvlUsd", 1) or 1

                html = (
                    _CSS
                    + '<div class="cb">'
                    '<div class="cb-hdr">'
                    f'<span class="cb-sym">💧 Ranking de Pools</span>'
                    f'<span class="cb-name">{par_input or "Top Geral"} · {chain_filter}</span>'
                    '<span class="cb-badge">DeFiLlama · Yields</span>'
                    '</div>'
                    '<div style="background:rgba(12,123,179,.06);border:1px solid rgba(12,123,179,.10);border-radius:16px;padding:8px 12px;'
                    'margin-bottom:12px;font-size:.75rem;color:#5f738b">'
                    '📐 <b style="color:#0c7bb3">Score LP</b> = '
                    '0.50 × (Vol/TVL) + 0.35 × APY_base − 0.15 × |IL_7d|'
                    '</div>'
                    '<table class="cb-tbl"><thead><tr>'
                    '<th>Pool</th><th>Score</th><th>APY Base</th>'
                    '<th>TVL</th><th>Vol 24h</th><th>IL 7d</th>'
                    f'</tr></thead><tbody>{rows}</tbody></table>'
                    '<div class="cb-g2" style="margin-top:12px">'
                    '<div class="cb-cell" style="text-align:left">'
                    '<div class="cb-clbl">📏 Faixa Recomendada (melhor pool)</div>'
                    f'<div style="font-weight:600;color:{b_cor};font-size:.9rem">{b_range}</div>'
                    f'<div style="font-size:.72rem;color:#5f738b;margin-top:3px">{b_range_desc}</div>'
                    '</div>'
                    '<div class="cb-cell" style="text-align:left">'
                    '<div class="cb-clbl">⚡ Vol/TVL (melhor pool)</div>'
                    f'<div style="font-weight:600;color:#4caf50;font-size:.9rem">{b_vol/b_tvl*100:.1f}%</div>'
                    '<div style="font-size:.72rem;color:#5f738b;margin-top:3px">Eficiência de capital</div>'
                    '</div></div>'
                    '<div class="cb-foot">🔄 DeFiLlama Yields · Tempo real</div>'
                    '</div>'
                )
                st.markdown(html, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao buscar pools: {e}")


# ─── Helper: extrai token base de um par (remove stables) ────────────────────
_STABLES = {"USDC", "USDT", "DAI", "USDC.E", "BUSD", "FRAX", "TUSD", "USDP", "LUSD", "CRVUSD", "USDE"}
_CMC_ALIAS = {"WBTC": "BTC", "WBTC.B": "BTC", "WETH": "ETH", "CBBTC": "BTC"}


def _token_base_do_par(symbol: str) -> str:
    """Extrai o token não-estável de um par (ex: 'WBTC-USDC' → 'BTC')."""
    partes = re.split(r"[-/.]", symbol.upper())
    for parte in partes:
        if parte not in _STABLES:
            return _CMC_ALIAS.get(parte, parte)
    return partes[0]


def _buscar_preco_cmc(simbolo: str) -> tuple[float, float] | None:
    """Retorna (preço_atual, volatilidade_7d%) via CoinMarketCap."""
    try:
        cmc   = CoinMarketCapAPI()
        data  = cmc.quotes_latest(simbolo)
        moeda = data.get("data", {}).get(simbolo, [{}])
        if isinstance(moeda, list):
            moeda = moeda[0] if moeda else {}
        elif isinstance(moeda, dict):
            moeda = next(iter(moeda.values()), {})
        quote = moeda.get("quote", {}).get("USD", {})
        preco = quote.get("price", 0) or 0
        vol_7d = abs(quote.get("percent_change_7d", 0) or 0)
        return (preco, vol_7d) if preco else None
    except Exception:
        return None


# ─── Tab 2: Calculadora de IL ─────────────────────────────────────────────────
def _tab_calculadora_il():
    st.markdown("### 📐 Calculadora de Impermanent Loss")
    st.caption("Baseada na fórmula fechada da Uniswap V2: $IL = \\frac{2\\sqrt{r}}{1+r} - 1$")

    # ── Seleção de par ────────────────────────────────────────────────────────
    pools_ranking: list = st.session_state.get("defi_ranking_pools", [])
    opcoes_par = [p.get("symbol", "") for p in pools_ranking if p.get("symbol")]
    opcoes_par = list(dict.fromkeys(opcoes_par))  # deduplica mantendo ordem

    if opcoes_par:
        opcoes_par_display = opcoes_par + ["✏️ Inserir manualmente"]
        st.info(
            f"💡 **{len(opcoes_par)} pares** carregados do Ranking. Selecione ou insira manualmente.",
            icon=None,
        )
        escolha = st.selectbox("Par de tokens", opcoes_par_display, index=0)
        if escolha == "✏️ Inserir manualmente":
            par_manual = st.text_input("Digite o par (ex: ETH/USDC, WBTC-USDC)").strip().upper()
            simbolo_base = _token_base_do_par(par_manual) if par_manual else ""
        else:
            simbolo_base = _token_base_do_par(escolha)
            st.caption(f"Token base detectado para cotação: **{simbolo_base}**")
    else:
        st.caption("💡 Use o **Ranking de Pools** primeiro para pré-carregar os pares, ou insira manualmente.")
        par_manual = st.text_input("Par de tokens (ex: ETH/USDC, WBTC-USDC)").strip().upper()
        simbolo_base = _token_base_do_par(par_manual) if par_manual else ""

    # ── Busca automática de preço ─────────────────────────────────────────────
    preco_live    = 0.0
    vol_7d_live   = 0.0
    preco_sugerido = 0.0

    if simbolo_base:
        cache_key = f"il_preco_{simbolo_base}"
        if cache_key not in st.session_state:
            with st.spinner(f"Buscando preço de {simbolo_base} na CoinMarketCap..."):
                resultado = _buscar_preco_cmc(simbolo_base)
                if resultado:
                    st.session_state[cache_key] = resultado
        cached = st.session_state.get(cache_key)
        if cached:
            preco_live, vol_7d_live = cached
            # Entrada sugerida = preço atual descontado pela volatilidade 7d (piso conservador)
            preco_sugerido = preco_live * (1 - vol_7d_live / 100)

    # ── Inputs editáveis ──────────────────────────────────────────────────────
    col_btn = st.columns([3, 1])
    with col_btn[1]:
        if simbolo_base and st.button("🔄 Atualizar preço", use_container_width=True):
            cache_key = f"il_preco_{simbolo_base}"
            if cache_key in st.session_state:
                del st.session_state[cache_key]
            st.rerun()

    if preco_live > 0:
        st.markdown(
            f'<div style="background:rgba(12,123,179,.06);border:1px solid rgba(12,123,179,.12);'
            f'border-radius:16px;padding:10px 14px;margin-bottom:10px;font-size:.82rem;color:#5f738b">'
            f'📡 <b style="color:#0c7bb3">{simbolo_base}</b> · '
            f'Preço atual: <b style="color:#10233a">{_fmt_usd(preco_live)}</b> · '
            f'Volatilidade 7d: <b style="color:#ff9800">{vol_7d_live:.1f}%</b> · '
            f'Entrada sugerida (−vol 7d): <b style="color:#4caf50">{_fmt_usd(preco_sugerido)}</b>'
            f'</div>',
            unsafe_allow_html=True,
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        preco_entrada = st.number_input(
            "Preço de entrada (US$)",
            min_value=0.0001,
            value=float(round(preco_sugerido, 2)) if preco_sugerido > 0 else 2000.0,
            step=max(1.0, round(preco_live * 0.001, 2)) if preco_live > 0 else 10.0,
            help="Pré-preenchido com preço atual − volatilidade 7d (sugestão conservadora). Edite à vontade.",
        )
    with col2:
        preco_atual = st.number_input(
            "Preço atual (US$)",
            min_value=0.0001,
            value=float(round(preco_live, 2)) if preco_live > 0 else 2400.0,
            step=max(1.0, round(preco_live * 0.001, 2)) if preco_live > 0 else 10.0,
            help="Pré-preenchido com cotação em tempo real via CoinMarketCap. Edite para simular cenários.",
        )
    with col3:
        capital = st.number_input("Capital investido (US$)", min_value=1.0, value=1000.0, step=100.0)

    if st.button("⚡ Calcular IL", use_container_width=True, type="primary"):
        il_pct = _calcular_il(preco_entrada, preco_atual)
        r = preco_atual / preco_entrada
        valor_lp   = capital * (2 * r ** 0.5 / (1 + r))
        valor_hodl = capital * (0.5 + 0.5 * r)
        perda_usd  = valor_lp - valor_hodl
        variacao_preco = (preco_atual / preco_entrada - 1) * 100

        il_cor   = "#4caf50" if il_pct > -1 else ("#ff9800" if il_pct > -5 else "#ef5350")
        il_label = "Baixo risco" if il_pct > -1 else ("Atenção" if il_pct > -5 else "Alto risco")

        html = (
            _CSS
            + '<div class="cb">'
            '<div class="cb-hdr">'
            '<span class="cb-sym">📐 Impermanent Loss</span>'
            f'<span class="cb-name">Entrada: {_fmt_usd(preco_entrada)} → Atual: {_fmt_usd(preco_atual)}</span>'
            f'<span class="cb-badge">{il_label}</span>'
            '</div>'
            '<div class="cb-lbl">📉 Impermanent Loss</div>'
            f'<div class="cb-big" style="color:{il_cor}">{il_pct:.2f}%</div>'
            '<div class="cb-g3">'
            '<div class="cb-cell"><div class="cb-clbl">📈 Variação do Preço</div>'
            f'<div class="cb-cval {_vc(variacao_preco)}">{_va(variacao_preco)} {abs(variacao_preco):.1f}%</div></div>'
            '<div class="cb-cell"><div class="cb-clbl">💰 Valor na LP</div>'
            f'<div class="cb-cval" style="color:#0c7bb3">{_fmt_usd(valor_lp)}</div></div>'
            '<div class="cb-cell"><div class="cb-clbl">🧊 Valor Hodl</div>'
            f'<div class="cb-cval" style="color:#10233a">{_fmt_usd(valor_hodl)}</div></div>'
            '</div>'
            '<div class="cb-g2">'
            '<div class="cb-cell" style="text-align:left"><div class="cb-clbl">💸 Perda vs Hodl</div>'
            f'<div style="font-weight:700;color:{il_cor};font-size:1.1rem">{_fmt_usd(perda_usd)}</div></div>'
            '<div class="cb-cell" style="text-align:left"><div class="cb-clbl">📊 Razão de Preço (r)</div>'
            f'<div style="font-weight:700;color:#10233a;font-size:1.1rem">{r:.4f}×</div></div>'
            '</div>'
            '<div class="cb-desc">'
            '💡 <b>Como interpretar:</b> O IL representa a diferença entre manter os ativos na pool vs. '
            'simplesmente segurá-los (hodl). Valores acima de -1% indicam baixo impacto; '
            'abaixo de -5% exigem fees altas para compensar.'
            '</div>'
            '<div class="cb-foot">🔄 Fórmula: IL = (2√r / (1+r)) − 1 · Uniswap V2 · Preço via CoinMarketCap</div>'
            '</div>'
        )
        st.markdown(html, unsafe_allow_html=True)


# ─── Tab 3: Range Optimizer ───────────────────────────────────────────────────
def _tab_range_optimizer():
    st.markdown("### 📏 Range Optimizer para Uniswap V3")
    st.caption("Sugere a faixa ideal de preço com base na volatilidade histórica do ativo.")

    col1, col2, col3 = st.columns(3)
    with col1:
        simbolo = st.text_input("Símbolo do token (ex: ETH, BTC, SOL)", value="ETH").strip().upper()
    with col2:
        fee_tier = st.selectbox("Fee Tier", ["0.05%", "0.3%", "1%"], index=1)
    with col3:
        capital_range = st.number_input("Capital (US$)", min_value=10.0, value=1000.0, step=100.0)

    if st.button("📏 Calcular Range", use_container_width=True, type="primary"):
        with st.spinner(f"Buscando dados de {simbolo}..."):
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
                nome = moeda.get("name", simbolo)

                if not preco:
                    st.error("Token não encontrado na CoinMarketCap.")
                    return

                faixa, desc, cor = _range_sugerido(vol_7d)
                fee_pct = float(fee_tier.replace("%", ""))

                # Calcula limites da faixa sugerida
                if "Estreita" in faixa:
                    delta = 0.05
                elif "Média" in faixa:
                    delta = 0.15
                else:
                    delta = 0.30

                preco_min = preco * (1 - delta)
                preco_max = preco * (1 + delta)

                # Estimativa diária de fees (simplificada)
                # fee_diaria ≈ capital × fee_tier × (vol_estimado_diario / tvl_estimado)
                # Usando proxy: vol_ratio ≈ vol_7d% * 0.3 como proxy conservador
                vol_ratio_proxy = min(vol_7d * 0.03, 0.5)
                fee_diaria_est = capital_range * fee_pct / 100 * vol_ratio_proxy

                # Prob. "in range" (heurística simples)
                prob_in_range = max(0.3, 1.0 - vol_7d / 100) * 100

                html = (
                    _CSS
                    + '<div class="cb">'
                    '<div class="cb-hdr">'
                    f'<span class="cb-sym">📏 {simbolo} — Range Optimizer</span>'
                    f'<span class="cb-name">{nome}</span>'
                    f'<span class="cb-badge">Fee {fee_tier}</span>'
                    '</div>'
                    '<div class="cb-lbl">💵 Preço Atual</div>'
                    f'<div class="cb-big">{_fmt_usd(preco)}</div>'
                    '<div class="cb-g3">'
                    '<div class="cb-cell">'
                    '<div class="cb-clbl">📉 Limite Inferior</div>'
                    f'<div class="cb-cval dn">{_fmt_usd(preco_min)}</div>'
                    '</div>'
                    '<div class="cb-cell">'
                    '<div class="cb-clbl">📈 Limite Superior</div>'
                    f'<div class="cb-cval up">{_fmt_usd(preco_max)}</div>'
                    '</div>'
                    '<div class="cb-cell">'
                    '<div class="cb-clbl">🎯 Prob. In Range</div>'
                    f'<div class="cb-cval" style="color:#ff9800">{prob_in_range:.0f}%</div>'
                    '</div>'
                    '</div>'
                    '<div class="cb-g2">'
                    '<div class="cb-cell" style="text-align:left">'
                    '<div class="cb-clbl">📏 Faixa Sugerida</div>'
                    f'<div style="font-weight:700;color:{cor};font-size:.95rem">{faixa}</div>'
                    f'<div style="font-size:.72rem;color:#5f738b;margin-top:3px">{desc}</div>'
                    '</div>'
                    '<div class="cb-cell" style="text-align:left">'
                    '<div class="cb-clbl">💸 Fee Diária Estimada</div>'
                    f'<div style="font-weight:700;color:#4caf50;font-size:.95rem">{_fmt_usd(fee_diaria_est)}</div>'
                    f'<div style="font-size:.72rem;color:#5f738b;margin-top:3px">Capital: {_fmt_usd(capital_range)}</div>'
                    '</div>'
                    '</div>'
                    '<div class="cb-cell" style="margin-top:8px;text-align:left">'
                    '<div class="cb-clbl">📊 Volatilidade 7d</div>'
                    f'<div style="font-weight:600;color:#ff9800">{vol_7d:.2f}%</div>'
                    '</div>'
                    '<div class="cb-desc">'
                    f'⚠️ <b>Atenção:</b> Faixas mais estreitas aumentam eficiência de capital e fees, '
                    f'mas saem do range com mais frequência. Com volatilidade de {vol_7d:.1f}% em 7 dias, '
                    f'a faixa <b>{faixa}</b> oferece melhor equilíbrio entre concentração e cobertura.'
                    '</div>'
                    '<div class="cb-foot">🔄 CoinMarketCap · Dados de volatilidade em tempo real</div>'
                    '</div>'
                )
                st.markdown(html, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao calcular range: {e}")


# ─── Tab 4: Stablecoins ───────────────────────────────────────────────────────
def _tab_stablecoins():
    st.markdown("### 🪙 Stablecoins do Mercado")
    st.caption("Principais stablecoins por supply circulante, mecanismo de peg e presença em chains.")

    col1, col2 = st.columns([1, 3])
    with col1:
        top_stable = st.selectbox("Exibir top", [10, 20, 30], index=0)
    with col2:
        filtro_mec = st.multiselect(
            "Filtrar por mecanismo",
            ["fiat-backed", "crypto-backed", "algorithmic", "hybrid"],
            default=[],
        )

    if st.button("🔍 Buscar Stablecoins", use_container_width=True, type="primary"):
        with st.spinner("Buscando stablecoins na DeFiLlama..."):
            try:
                llama = DefiLlamaAPI()
                data = llama.stablecoins()
                moedas = data.get("peggedAssets", []) if isinstance(data, dict) else []
                if not moedas:
                    st.error("Sem dados disponíveis.")
                    return

                if filtro_mec:
                    moedas = [m for m in moedas if m.get("pegMechanism", "") in filtro_mec]

                moedas = sorted(
                    moedas,
                    key=lambda x: x.get("circulating", {}).get("peggedUSD", 0),
                    reverse=True,
                )[:top_stable]

                rows = ""
                total_supply = sum(
                    m.get("circulating", {}).get("peggedUSD", 0) for m in moedas
                )
                for m in moedas:
                    nome     = m.get("name", "")
                    sym      = m.get("symbol", "")
                    peg_type = m.get("pegType", "")
                    peg_mech = m.get("pegMechanism", "")
                    supply   = m.get("circulating", {}).get("peggedUSD", 0) or 0
                    n_chains = len(m.get("chains", []))
                    dominance = supply / total_supply * 100 if total_supply else 0
                    mech_cor = (
                        "#4caf50" if peg_mech == "fiat-backed"
                        else "#ff9800" if peg_mech == "crypto-backed"
                        else "#ef5350"
                    )
                    rows += (
                        f'<tr>'
                        f'<td><b>{nome}</b> <span style="color:#5f738b;font-size:.72rem">{sym}</span></td>'
                        f'<td style="color:#5f738b;font-size:.78rem">{peg_type}</td>'
                        f'<td><span style="color:{mech_cor};font-size:.75rem;font-weight:600">{peg_mech}</span></td>'
                        f'<td style="font-weight:600">{_fmt_usd(supply)}</td>'
                        f'<td style="color:#0c7bb3">{dominance:.1f}%</td>'
                        f'<td style="color:#0c7bb3;text-align:center">{n_chains}</td>'
                        f'</tr>'
                    )

                html = (
                    _CSS
                    + '<div class="cb">'
                    '<div class="cb-hdr">'
                    f'<span class="cb-sym">🪙 Top {top_stable} Stablecoins</span>'
                    f'<span class="cb-badge">DeFiLlama</span>'
                    '</div>'
                    '<div class="cb-g3" style="margin-bottom:12px">'
                    '<div class="cb-cell">'
                    '<div class="cb-clbl">Supply Total</div>'
                    f'<div class="cb-cval" style="color:#0c7bb3">{_fmt_usd(total_supply)}</div>'
                    '</div>'
                    f'<div class="cb-cell"><div class="cb-clbl">Ativos</div>'
                    f'<div class="cb-cval" style="color:#10233a">{len(moedas)}</div></div>'
                    f'<div class="cb-cell"><div class="cb-clbl">Mecanismos</div>'
                    f'<div class="cb-cval" style="color:#10233a">'
                    f'{len(set(m.get("pegMechanism","") for m in moedas))}</div></div>'
                    '</div>'
                    '<table class="cb-tbl"><thead><tr>'
                    '<th>Ativo</th><th>Peg</th><th>Mecanismo</th>'
                    '<th>Supply</th><th>Dominância</th><th>Chains</th>'
                    f'</tr></thead><tbody>{rows}</tbody></table>'
                    '<div class="cb-foot">🔄 DeFiLlama · Tempo real</div>'
                    '</div>'
                )
                st.markdown(html, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao buscar stablecoins: {e}")


# ─── Página principal ─────────────────────────────────────────────────────────
def showDefiPools():
    st.markdown(
        _CSS
        + "<div class='defi-hero'>"
        + "<h2 class='defi-title'>💧 DeFi & Pools</h2>"
        + "<p class='defi-copy'>Análise inteligente de pools de liquidez, impermanent loss e stablecoins em tempo real.</p>"
        + "</div>",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3, tab4 = st.tabs([
        "🏆 Ranking de Pools",
        "📐 Calculadora de IL",
        "📏 Range Optimizer",
        "🪙 Stablecoins",
    ])

    with tab1:
        _tab_ranking()

    with tab2:
        _tab_calculadora_il()

    with tab3:
        _tab_range_optimizer()

    with tab4:
        _tab_stablecoins()
