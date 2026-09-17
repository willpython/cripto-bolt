r"""
Preparacao e Preview de Pool BCH/BlockSniper — Agente Cripto Bolt.

MODO ESTRITAMENTE SOMENTE LEITURA em relacao a NiceHash:
- Usa apenas GET /main/api/v2/pools para checar duplicidade.
- NUNCA envia POST /main/api/v2/pools.
- NUNCA cria, edita ou remove qualquer pool.

Este script:
  1. Le host/porta/username/password/nome da pool via variaveis de
     ambiente (.env), nunca hardcoded, nunca impresso em texto puro.
  2. Valida o formato de cada campo.
  3. Consulta as pools existentes na conta (GET) para detectar duplicidade
     por host+porta.
  4. Monta o payload que SERIA enviado a POST /main/api/v2/pools, com
     username/password mascarados no log e no Telegram.
  5. Envia um resumo ao Telegram (opcional).
  6. NAO cria a pool. A criacao real sera uma etapa futura, separada,
     com confirmacao explicita.

Variaveis de ambiente esperadas (.env):
    BLOCKSNIPER_POOL_NAME=BlockSniper-BCH-Solo
    BLOCKSNIPER_STRATUM_HOST=solo.blocksniper.exemplo.com
    BLOCKSNIPER_STRATUM_PORT=3333
    BLOCKSNIPER_WORKER_USERNAME=142xxxxxxx
    BLOCKSNIPER_WORKER_PASSWORD=x

Execute a partir da raiz do projeto:
    python testes/preparar_pool_blocksniper.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEND_TELEGRAM_NOTIFICATION = True

# Algoritmo fixo desta pool: SHA256 (BCH via NiceHash SHA256 marketplace).
POOL_ALGORITHM = "SHA256"

HOSTNAME_PATTERN = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)+$"
)


@dataclass
class PoolConfig:
    """Configuracao de pool lida do .env. Nunca serializar password em texto puro."""

    name: str
    host: str
    port: int
    username: str
    password: str


@dataclass
class PoolValidationResult:
    """Resultado da validacao/preview. is_valid=False bloqueia qualquer preview de criacao."""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_found: bool = False
    existing_pools_count: int = 0
    preview_payload: Optional[dict[str, Any]] = None


def mask_secret(value: str, keep_start: int = 3, keep_end: int = 2) -> str:
    """Mascara um valor sensivel, preservando poucos caracteres nas pontas para conferencia visual."""
    if not value:
        return "(vazio)"
    length = len(value)
    if length <= keep_start + keep_end:
        return "*" * length
    return f"{value[:keep_start]}{'*' * (length - keep_start - keep_end)}{value[-keep_end:]}"


def load_pool_config_from_env() -> Optional[PoolConfig]:
    """Le a configuracao de pool do .env. Retorna None se algum campo obrigatorio faltar."""
    name = os.getenv("BLOCKSNIPER_POOL_NAME", "").strip()
    host = os.getenv("BLOCKSNIPER_STRATUM_HOST", "").strip()
    port_raw = os.getenv("BLOCKSNIPER_STRATUM_PORT", "").strip()
    username = os.getenv("BLOCKSNIPER_WORKER_USERNAME", "").strip()
    password = os.getenv("BLOCKSNIPER_WORKER_PASSWORD", "").strip()

    missing = [
        field_name
        for field_name, value in (
            ("BLOCKSNIPER_POOL_NAME", name),
            ("BLOCKSNIPER_STRATUM_HOST", host),
            ("BLOCKSNIPER_STRATUM_PORT", port_raw),
            ("BLOCKSNIPER_WORKER_USERNAME", username),
        )
        if not value
    ]
    if missing:
        print(f"[ERRO] Variaveis ausentes no .env: {', '.join(missing)}")
        return None

    try:
        port = int(port_raw)
    except ValueError:
        print("[ERRO] BLOCKSNIPER_STRATUM_PORT precisa ser um inteiro. Valor atual invalido.")
        return None

    return PoolConfig(name=name, host=host, port=port, username=username, password=password)


def validate_pool_config(config: PoolConfig) -> PoolValidationResult:
    """Valida formato dos campos, sem qualquer chamada de rede."""
    result = PoolValidationResult()

    if not (1 <= len(config.name) <= 64):
        result.errors.append("Nome da pool deve ter entre 1 e 64 caracteres.")

    if not HOSTNAME_PATTERN.match(config.host):
        result.errors.append(
            f"Hostname '{config.host[:3]}...' nao parece um dominio valido "
            f"(esperado algo como solo.blocksniper.exemplo.com)."
        )

    if not (1 <= config.port <= 65535):
        result.errors.append(f"Porta {config.port} fora do intervalo valido (1-65535).")

    if config.port not in (3333, 4444, 443, 8443, 5000, 5555, 9999):
        result.warnings.append(
            f"Porta {config.port} nao e uma das portas Stratum mais comuns "
            f"(3333/4444/443/8443/5000/5555/9999). Confirme com a documentacao do BlockSniper."
        )

    if len(config.username) < 3:
        result.errors.append("Worker username muito curto (menos de 3 caracteres).")

    if not config.password:
        result.warnings.append(
            "Password vazio. Muitas pools SHA256 aceitam 'x' como password padrao; confirme com o BlockSniper."
        )

    result.is_valid = len(result.errors) == 0
    return result


async def check_duplicate_pool(client: Any, config: PoolConfig) -> tuple[bool, int]:
    """
    Consulta GET /main/api/v2/pools e verifica se ja existe uma pool
    com o mesmo host+porta cadastrada. Retorna (duplicado, total_pools).
    """
    response = await client._request(
        "GET", "/main/api/v2/pools", params={"page": 0, "size": 100}
    )
    pools = response.get("list", response.get("pools", []))
    if not isinstance(pools, list):
        pools = []

    for pool in pools:
        stratum_hostname = str(pool.get("stratumHostname", pool.get("host", ""))).strip().lower()
        stratum_port = pool.get("stratumPort", pool.get("port"))
        if stratum_hostname == config.host.strip().lower() and str(stratum_port) == str(config.port):
            return True, len(pools)

    return False, len(pools)


def build_preview_payload(config: PoolConfig) -> dict[str, Any]:
    """
    Monta o payload que SERIA enviado para POST /main/api/v2/pools.
    Este payload NUNCA e enviado por este script.
    """
    return {
        "algorithm": POOL_ALGORITHM,
        "name": config.name,
        "username": mask_secret(config.username),
        "password": mask_secret(config.password) if config.password else "(vazio)",
        "stratumHostname": config.host,
        "stratumPort": config.port,
        "_status": "PREVIEW_ONLY",
        "_warning": "Este payload NAO foi enviado. Nenhuma pool foi criada por este script.",
    }


async def notify_telegram(config: PoolConfig, validation: PoolValidationResult) -> bool:
    """Envia um resumo de preview ao Telegram. Falha aqui nunca bloqueia o script."""
    if not SEND_TELEGRAM_NOTIFICATION:
        return False

    try:
        from core.telegram_bolt import TelegramNotifier
    except ImportError as exc:
        print(f"[AVISO] Telegram nao integrado: {exc}")
        return False

    method = getattr(TelegramNotifier, "notificar_preview_pool", None)
    if method is None:
        print(
            "[AVISO] TelegramNotifier.notificar_preview_pool ainda nao existe. "
            "Pulei a notificacao Telegram desta etapa."
        )
        return False

    payload = {
        "pool_name": config.name,
        "algorithm": POOL_ALGORITHM,
        "host": config.host,
        "port": config.port,
        "username_masked": mask_secret(config.username),
        "is_valid": validation.is_valid,
        "duplicate_found": validation.duplicate_found,
        "existing_pools_count": validation.existing_pools_count,
        "errors": validation.errors,
        "warnings": validation.warnings,
    }

    try:
        return bool(await method(payload))
    except Exception as exc:
        print(f"[AVISO] Falha ao enviar preview ao Telegram: {type(exc).__name__}: {exc}")
        return False


async def main() -> int:
    print(f"[INFO] Raiz do projeto: {ROOT}")
    print("[INFO] Modo seguro: apenas GET para checar duplicidade. Nenhuma pool sera criada.\n")

    try:
        from exchanges.mineracao_bitcoin.cripto_bolt_parte4 import load_nicehash_env
        from exchanges.mineracao_bitcoin.cripto_bolt_parte3 import NiceHashHMACClient
    except ImportError as exc:
        print(f"[ERRO] Falha ao importar modulos Cripto Bolt: {exc}")
        return 1

    try:
        env_status = load_nicehash_env(ROOT / ".env")
    except RuntimeError as exc:
        print(f"[ERRO] {exc}")
        return 1

    if not env_status.get("all_present", False):
        print("[ERRO] Credenciais NiceHash incompletas no .env.")
        return 1

    config = load_pool_config_from_env()
    if config is None:
        print("\n[ERRO] Configure as variaveis BLOCKSNIPER_* no .env antes de continuar.")
        return 1

    print("=== Configuracao lida do .env (valores mascarados) ===")
    print(f"Nome da pool:      {config.name}")
    print(
        f"Hostname:          "
        f"{config.host[:3]}{'*' * max(len(config.host) - 5, 0)}"
        f"{config.host[-2:] if len(config.host) > 5 else ''}"
    )
    print(f"Porta:             {config.port}")
    print(f"Worker username:   {mask_secret(config.username)}")
    print(f"Password:          {mask_secret(config.password) if config.password else '(vazio)'}")

    validation = validate_pool_config(config)

    if validation.errors:
        print("\n[ERRO] Configuracao invalida:")
        for error in validation.errors:
            print(f"  - {error}")

    if validation.warnings:
        print("\n[AVISO] Pontos de atencao:")
        for warning in validation.warnings:
            print(f"  - {warning}")

    if not validation.is_valid:
        print("\n[BLOQUEADO] Corrija os erros acima antes de prosseguir. Nenhuma consulta de duplicidade foi feita.")
        await notify_telegram(config, validation)
        return 1

    try:
        async with NiceHashHMACClient() as client:
            duplicate, total_pools = await check_duplicate_pool(client, config)
    except Exception as exc:
        print(f"\n[ERRO] Falha ao consultar pools existentes (GET): {type(exc).__name__}: {exc}")
        return 1

    validation.duplicate_found = duplicate
    validation.existing_pools_count = total_pools

    print("\n=== Verificacao de duplicidade (GET, somente leitura) ===")
    print(f"Pools existentes na conta: {total_pools}")
    print(f"Duplicidade detectada:     {'SIM' if duplicate else 'NAO'}")

    if duplicate:
        print(
            "\n[BLOQUEADO] Ja existe uma pool cadastrada com este mesmo host e porta. "
            "Nenhum novo preview de criacao foi gerado para evitar duplicidade."
        )
        await notify_telegram(config, validation)
        return 1

    validation.preview_payload = build_preview_payload(config)

    print("\n=== Preview do payload de criacao (NAO ENVIADO) ===")
    for key, value in validation.preview_payload.items():
        print(f"{key}: {value}")

    sent = await notify_telegram(config, validation)
    if sent:
        print("\n[OK] Preview enviado ao Telegram para sua revisao.")
    elif SEND_TELEGRAM_NOTIFICATION:
        print("\n[AVISO] Preview calculado, mas nao foi possivel notificar via Telegram.")

    print("\n" + "=" * 78)
    print("GARANTIA: nenhuma requisicao POST, PUT, PATCH ou DELETE foi executada.")
    print("A criacao real desta pool exige uma etapa separada e sua confirmacao explicita.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
