import os
import sys
from dotenv import load_dotenv
import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not TOKEN:
    print("❌ ERRO: 'TELEGRAM_BOT_TOKEN' não está preenchido no arquivo .env!")
    sys.exit(1)


def consultar_telegram():
    print(f"🤖 Consultando API do Telegram com o Token configurado...\n")

    # 1. Informações do Bot
    url_me = f"https://api.telegram.org/bot{TOKEN}/getMe"
    try:
        res_me = requests.get(url_me, timeout=10).json()
        if not res_me.get("ok"):
            print(f"❌ Token inválido ou erro na API:\n{res_me}")
            return

        bot_info = res_me["result"]
        print("✅ BOT IDENTIFICADO COM SUCESSO:")
        print(f"   • Nome: {bot_info.get('first_name')}")
        print(f"   • Username: @{bot_info.get('username')}")
        print(f"   • Bot ID: {bot_info.get('id')}\n")

    except Exception as e:
        print(f"❌ Erro de conexão com a API do Telegram: {e}")
        return

    # 2. Informações de Mensagens Recentes (Chat ID)
    url_updates = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        res_updates = requests.get(url_updates, timeout=10).json()
        updates = res_updates.get("result", [])

        if not updates:
            print("⚠️ Nenhuma mensagem encontrada nas últimas interações!")
            print(
                f"👉 Vá no Telegram, abra uma conversa com @{bot_info.get('username')} e envie qualquer mensagem (ex: /start)."
            )
            print("   Depois, execute este script novamente para capturar o seu CHAT_ID.\n")
            return

        ultima_msg = updates[-1]
        msg_obj = ultima_msg.get("message") or ultima_msg.get(
            "channel_post", {}
        )
        chat = msg_obj.get("chat", {})
        remetente = msg_obj.get("from", {})

        print("🎯 SEU TELEGRAM_CHAT_ID ENCONTRADO:")
        print(f"   • TELEGRAM_CHAT_ID = {chat.get('id')}")
        print(
            f"   • Remetente: {remetente.get('first_name')} (@{remetente.get('username')})"
        )
        print(f"   • Texto recebido: '{msg_obj.get('text')}'")
        print("\n📝 Copie o número acima e cole no seu .env em 'TELEGRAM_CHAT_ID'!")

    except Exception as e:
        print(f"❌ Erro ao buscar updates: {e}")


if __name__ == "__main__":
    consultar_telegram()