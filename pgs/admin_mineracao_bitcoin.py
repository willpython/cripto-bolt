"""
Pagina Streamlit de administracao do Agente Cripto Bolt (mineracao BCH).
Segue o padrao show*() usado nas demais paginas do projeto (pgs/*.py).

Secoes:
  1. Status das credenciais NiceHash (.env) — nunca exibe valores reais.
  2. Teste de conectividade real (somente leitura).
  3. NOVO: Configuracao e criacao de Pool BCH/BlockSniper, com preview
     obrigatorio e confirmacao explicita antes de qualquer POST real.
  4. Limites de risco e estado atual do agente (SQLite assincrono).
  5. Ciclo manual simulado (NiceHashClient mock, nunca envia ordem real).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import streamlit as st

from exchanges.mineracao_bitcoin.cripto_bolt_parte1 import (
    RiskLimits,
    MarketSnapshot,
    SpreadOpportunity,
    NetworkSnapshot,
)
from exchanges.mineracao_bitcoin.cripto_bolt_parte2 import (
    evaluate_position,
    execute_action,
    NiceHashClient,
)
from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import (
    SQLAlchemyRentalStateStore,
    NiceHashHMACClient,
)
from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import (
    load_nicehash_env,
    test_nicehash_connectivity as _test_conn,
)
import os

POOL_ALGORITHM = "SHA256"


def _get_store() -> SQLAlchemyRentalStateStore:
    if "cripto_bolt_store" not in st.session_state:
        st.session_state["cripto_bolt_store"] = SQLAlchemyRentalStateStore(
            "cripto_bolt_mineracao.db"
        )
    return st.session_state["cripto_bolt_store"]


def _mask_secret(value: str, keep_start: int = 3, keep_end: int = 2) -> str:
    """Mascara um valor sensivel, preservando poucos caracteres nas pontas."""
    if not value:
        return "(vazio)"
    length = len(value)
    if length <= keep_start + keep_end:
        return "*" * length
    return f"{value[:keep_start]}{'*' * (length - keep_start - keep_end)}{value[-keep_end:]}"


async def _fetch_existing_pools() -> list[dict[str, Any]]:
    """Consulta GET /main/api/v2/pools. Somente leitura, nunca cria/edita/remove."""
    async with NiceHashHMACClient() as client:
        response = await client._request(
            "GET", "/main/api/v2/pools", params={"page": 0, "size": 100}
        )
    pools = response.get("list", response.get("pools", []))
    return pools if isinstance(pools, list) else []


def _check_duplicate(pools: list[dict[str, Any]], host: str, port: int) -> bool:
    host_norm = host.strip().lower()
    for pool in pools:
        stratum_host = str(pool.get("stratumHostname", pool.get("host", ""))).strip().lower()
        stratum_port = pool.get("stratumPort", pool.get("port"))
        if stratum_host == host_norm and str(stratum_port) == str(port):
            return True
    return False


async def _create_pool_real(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Cria uma pool real na conta NiceHash.

    Endpoint oficial:
        POST /main/api/v2/pool

    Esta é a única operação de escrita nesta página. Ela só deve ser
    chamada após a confirmação explícita do operador na interface.
    """
    async with NiceHashHMACClient() as client:
        return await client._request(
            "POST",
            "/main/api/v2/pool",
            json_body=payload,
        )


def _render_pool_configuration_section() -> None:
    """
    Secao de configuracao e criacao de Pool BCH/BlockSniper.

    Fluxo de seguranca em 3 etapas na UI:
      1. Preencher os campos e clicar em "Validar e Gerar Preview".
      2. Revisar o preview (com credenciais mascaradas) e o resultado
         da checagem de duplicidade (GET real).
      3. Marcar a caixa de confirmacao explicita + clicar em
         "Criar Pool na NiceHash" para disparar o UNICO POST desta secao.
    """
    st.subheader("🏗️ Configurar Pool BCH/BlockSniper")
    st.caption(
        "Cadastre o destino Stratum da mineração solo BCH. "
        "Esta ação não gasta BTC e não abre nenhum rental — apenas registra "
        "um destino de mineração na sua conta NiceHash."
    )

    default_pool_name = os.getenv(
    "BLOCKSNIPER_POOL_NAME",
    "BlockSniper-BCH-Solo",
    )

    default_stratum_host = os.getenv(
        "BLOCKSNIPER_STRATUM_HOST",
        "",
    ).strip()

    default_stratum_port = int(
        os.getenv("BLOCKSNIPER_STRATUM_PORT", "3333")
    )

    default_worker_username = os.getenv(
        "BLOCKSNIPER_WORKER_USERNAME",
        "",
    ).strip()

    default_worker_password = os.getenv(
        "BLOCKSNIPER_WORKER_PASSWORD",
        "",
    ).strip()
    
    with st.form("form_pool_blocksniper", clear_on_submit=False):
        pool_name = st.text_input(
            "Nome da pool",
            value=st.session_state.get("pool_name_draft", default_pool_name),
        )
        stratum_host = st.text_input(
            "Hostname Stratum (sem protocolo, sem porta)",
            value=st.session_state.get("pool_host_draft", default_stratum_host),
            placeholder="solo.blocksniper.ai",
        )
        stratum_port = st.number_input(
            "Porta Stratum",
            min_value=1,
            max_value=65535,
            value=int(st.session_state.get("pool_port_draft", default_stratum_port)),
        )
        worker_username = st.text_input(
            "Worker username",
            value=st.session_state.get(
                "pool_username_draft",
                default_worker_username,
            ),
            type="password",
        )
        worker_password = st.text_input(
            "Password",
            value=st.session_state.get(
                "pool_password_draft",
                default_worker_password,
            ),
            type="password",
        )

        validate_clicked = st.form_submit_button("1️⃣ Validar e Gerar Preview")

    if validate_clicked:
        st.session_state["pool_name_draft"] = pool_name
        st.session_state["pool_host_draft"] = stratum_host.strip()
        st.session_state["pool_port_draft"] = int(stratum_port)
        st.session_state["pool_username_draft"] = worker_username
        st.session_state["pool_password_draft"] = worker_password

        errors: list[str] = []
        warnings: list[str] = []

        host_clean = stratum_host.strip()
        if "://" in host_clean:
            errors.append("Remova o protocolo (ex: 'stratum+tcp://') do campo Hostname.")
        if ":" in host_clean:
            errors.append("Remova a porta embutida do Hostname; use o campo Porta separadamente.")
        if "." not in host_clean or len(host_clean) < 4:
            errors.append("Hostname não parece um domínio válido (ex: solo.blocksniper.ai).")
        if len(worker_username.strip()) < 3:
            errors.append("Worker username muito curto (mínimo 3 caracteres).")
        if not worker_password:
            warnings.append("Password vazio. Muitas pools aceitam 'x' como padrão.")
        if int(stratum_port) not in (3333, 4444, 443, 8443, 5000, 5555, 9999):
            warnings.append(
                f"Porta {int(stratum_port)} não é uma das portas Stratum mais comuns. Confirme com o BlockSniper."
            )

        st.session_state["pool_validation_errors"] = errors
        st.session_state["pool_validation_warnings"] = warnings
        st.session_state["pool_preview_ready"] = len(errors) == 0
        st.session_state["pool_duplicate_checked"] = False

    errors = st.session_state.get("pool_validation_errors", [])
    warnings = st.session_state.get("pool_validation_warnings", [])

    if errors:
        st.error("Corrija os erros abaixo antes de continuar:")
        for error in errors:
            st.write(f"- {error}")

    if warnings:
        st.warning("Pontos de atenção:")
        for warning in warnings:
            st.write(f"- {warning}")

    if st.session_state.get("pool_preview_ready"):
        host = st.session_state["pool_host_draft"]
        port = st.session_state["pool_port_draft"]
        username = st.session_state["pool_username_draft"]
        password = st.session_state["pool_password_draft"]
        name = st.session_state["pool_name_draft"]

        st.success("Formato validado. Revise o preview mascarado abaixo.")
        st.markdown("**Preview (credenciais mascaradas):**")
        st.json(
            {
                "algorithm": POOL_ALGORITHM,
                "name": name,
                "username": _mask_secret(username),
                "password": _mask_secret(password) if password else "(vazio)",
                "stratumHostname": host,
                "stratumPort": port,
                "_status": "PREVIEW_ONLY",
            }
        )

        if st.button("2️⃣ Verificar Duplicidade na NiceHash (GET)"):
            with st.spinner("Consultando pools existentes (somente leitura)..."):
                try:
                    pools = asyncio.run(_fetch_existing_pools())
                    duplicate = _check_duplicate(pools, host, port)
                    st.session_state["pool_existing_count"] = len(pools)
                    st.session_state["pool_duplicate_found"] = duplicate
                    st.session_state["pool_duplicate_checked"] = True
                except Exception as exc:
                    st.error(f"Falha ao consultar pools existentes: {type(exc).__name__}: {exc}")
                    st.session_state["pool_duplicate_checked"] = False

        if st.session_state.get("pool_duplicate_checked"):
            existing_count = st.session_state.get("pool_existing_count", 0)
            duplicate_found = st.session_state.get("pool_duplicate_found", False)

            st.info(f"Pools existentes na conta: {existing_count}")

            if duplicate_found:
                st.error(
                    "⚠️ Já existe uma pool cadastrada com este mesmo host e porta. "
                    "A criação foi bloqueada para evitar duplicidade."
                )
            else:
                st.success("Nenhuma duplicidade encontrada. Pronto para criação real.")

                st.markdown("---")
                st.markdown("**⚠️ Revisão final antes do envio real (POST):**")
                st.warning(
                    "Esta ação é irreversível neste sentido: a pool ficará registrada "
                    "permanentemente na sua conta NiceHash. Ela não gasta BTC nem abre "
                    "rental, mas fica disponível para uso em ordens futuras."
                )

                confirm_checkbox = st.checkbox(
                    "Confirmo que revisei os dados e quero criar esta pool na NiceHash agora.",
                    key="pool_confirm_checkbox",
                )

                if st.button(
                    "3️⃣ Criar Pool na NiceHash",
                    type="primary",
                    disabled=not confirm_checkbox,
                ):
                    real_payload = {
                        "algorithm": POOL_ALGORITHM,
                        "name": name,
                        "username": username,
                        "password": password or "x",
                        "stratumHostname": host,
                        "stratumPort": port,
                    }
                    with st.spinner("Enviando POST /main/api/v2/pools..."):
                        try:
                            response = asyncio.run(_create_pool_real(real_payload))
                            pool_id = response.get("id", "desconhecido")
                            st.success(f"✅ Pool criada com sucesso! ID: {pool_id}")
                            st.json(
                                {
                                    "id": pool_id,
                                    "name": response.get("name", name),
                                    "algorithm": response.get("algorithm", POOL_ALGORITHM),
                                }
                            )
                            st.session_state["pool_preview_ready"] = False
                            st.session_state["pool_duplicate_checked"] = False

                            try:
                                from core.telegram_bolt import TelegramNotifier

                                method = getattr(TelegramNotifier, "notificar_pool_criada", None)
                                if method:
                                    asyncio.run(
                                        method(
                                            {
                                                "pool_id": pool_id,
                                                "pool_name": name,
                                                "algorithm": POOL_ALGORITHM,
                                                "host": host,
                                                "port": port,
                                            }
                                        )
                                    )
                            except Exception:
                                pass

                        except Exception as exc:
                            st.error(f"Falha ao criar a pool: {type(exc).__name__}: {exc}")


def showAdminMineracaoBitcoin() -> None:
    st.title("⛏️ Agente Cripto Bolt — Mineração BCH (Rental-First)")
    st.caption("BlockSniper + SpreadHunter + NiceHash · MaxProfit & AI StopLoss")

    env_status = load_nicehash_env()
    col1, col2, col3 = st.columns(3)
    col1.metric("API Key", "OK" if env_status["api_key_set"] else "Ausente")
    col2.metric("API Secret", "OK" if env_status["api_secret_set"] else "Ausente")
    col3.metric("Org ID", "OK" if env_status["org_id_set"] else "Ausente")

    st.divider()
    st.subheader("Teste de Conectividade (somente leitura)")
    if st.button("Testar conexão real com NiceHash", disabled=not env_status["all_present"]):
        with st.spinner("Consultando saldo via API real (sem criar ordens)..."):
            result = asyncio.run(_test_conn())
        if result["success"]:
            st.success(f"Conectado! Saldo disponível: {result['balance_btc']:.8f} BTC")
        else:
            st.error(f"Falha na conexão: {result['error']}")

    st.divider()
    _render_pool_configuration_section()

    st.divider()
    st.subheader("Limites de Risco")
    budget = st.number_input("Budget (USD)", min_value=1.0, value=50.0, step=10.0)
    max_loss_usd = st.number_input("Perda máxima (USD) — AI StopLoss", min_value=1.0, value=5.0, step=1.0)
    target_roi = st.number_input("ROI mínimo esperado (%)", min_value=0.1, value=15.0, step=1.0)

    st.divider()
    st.subheader("Estado Atual do Agente")
    store = _get_store()
    state = store.to_state_dict()
    st.json(state)

    st.divider()
    st.subheader("Rodar Ciclo Manual (modo simulado)")
    st.caption(
        "Usa NiceHashClient MOCK para este ciclo manual — não envia ordens reais. "
        "O agent_loop automático (via NICEHASH_API_KEY configurada) usa o cliente real."
    )
    if st.button("Executar 1 ciclo de decisão (simulado)"):
        opp = SpreadOpportunity(
            opportunity_id="opp-manual-ui",
            provider="NiceHash",
            payout_destination="BlockSniper-Solo-BCH",
            hashpower_ph=400.0,
            rental_price_usd_per_ph_day=100.0,
            estimated_payout_usd_per_ph_day=140.0,
        )
        market = MarketSnapshot(opportunities=[opp])
        network = NetworkSnapshot(
            network_hashrate_ph=3200.0, difficulty=450_000_000_000.0,
            last_block_height=850000, seconds_since_last_block=300.0,
        )
        limits = RiskLimits(budget_usd=budget, max_loss_usd=max_loss_usd, target_roi_pct=target_roi)

        result = evaluate_position(market, network, limits, current_order=store.active_order())
        order = asyncio.run(execute_action(result, market, store=store, provider_client=NiceHashClient()))

        st.info(f"Decisão: **{result.decision.value}**")
        st.write(result.rationale)
        if order:
            st.json(order.model_dump(mode="json"))
