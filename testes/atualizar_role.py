@'
import sys

legacy_address = "142Aqbuq23GyLQskYeqmnaGhXFJM6xS1jE".strip()
alphabet = set("142Aqbuq23GyLQskYeqmnaGhXFJM6xS1jE")

if legacy_address == "142Aqbuq23GyLQskYeqmnaGhXFJM6xS1jE":
    print("FALHOU: substitua o marcador localmente.")
    sys.exit(1)

invalid = [
    (index, char)
    for index, char in enumerate(legacy_address)
    if char not in alphabet
]

print(f"comprimento={len(legacy_address)}")
print(f"primeiro_caractere={legacy_address[0] if legacy_address else 'vazio'}")

if invalid:
    positions = ", ".join(str(index) for index, _ in invalid)
    categories = sorted({repr(char) for _, char in invalid})
    print("FALHOU: caracteres invalidos encontrados.")
    print("posicoes_invalidas=" + positions)
    print("caracteres_invalidos=" + ", ".join(categories))
    sys.exit(1)

if legacy_address[0] not in ("1", "3"):
    print("FALHOU: o endereco nao inicia com 1 ou 3; nao parece Base58 BCH mainnet.")
    sys.exit(1)

print("OK: caracteres Base58 aprovados; prossiga repetindo o conversor offline anterior.")
'@ | python