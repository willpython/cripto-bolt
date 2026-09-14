import logging
import os
import smtplib
import ssl
from datetime import datetime
from html import escape
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from settings import get_setting


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)
DEFAULT_SMTP_TIMEOUT = 20
_email_scheduler: BackgroundScheduler | None = None

LOGO_PATH = os.path.join(os.path.dirname(__file__), 'src', 'img', 'cripto-bolt.png')


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'sim'}


class Notificador:
    """
    Envia e-mails por SMTP.

    Configuração esperada em st.secrets ([email]) ou .env:
    - EMAIL_HOST
    - EMAIL_PORT
    - EMAIL_USERNAME
    - EMAIL_PASSWORD
    - EMAIL_USE_TLS
    - EMAIL_USE_SSL
    - EMAIL_REMETENTE
    """

    def __init__(self):
        smtp_port = get_setting('EMAIL_PORT')
        self.smtp_host = get_setting('EMAIL_HOST')
        self.smtp_port = int(smtp_port) if smtp_port else 0
        self.smtp_username = get_setting('EMAIL_USERNAME')
        self.smtp_password = get_setting('EMAIL_PASSWORD')
        self.smtp_use_tls = _as_bool(get_setting('EMAIL_USE_TLS'), default=True)
        self.smtp_use_ssl = _as_bool(get_setting('EMAIL_USE_SSL'), default=False)
        self.sender_email = get_setting('EMAIL_REMETENTE') or self.smtp_username

    def _validate_email_config(self):
        if not self.smtp_host or not self.smtp_port:
            raise RuntimeError('EMAIL_HOST ou EMAIL_PORT não configurado.')
        if not self.sender_email:
            raise RuntimeError('EMAIL_REMETENTE ou EMAIL_USERNAME não configurado.')
        if self.smtp_use_tls and self.smtp_use_ssl:
            raise RuntimeError('EMAIL_USE_TLS e EMAIL_USE_SSL não podem estar ativos ao mesmo tempo.')

    def _open_smtp_connection(self):
        self._validate_email_config()
        context = ssl.create_default_context()

        if self.smtp_use_ssl:
            server = smtplib.SMTP_SSL(
                self.smtp_host,
                self.smtp_port,
                timeout=DEFAULT_SMTP_TIMEOUT,
                context=context,
            )
        else:
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=DEFAULT_SMTP_TIMEOUT)
            server.ehlo()
            if self.smtp_use_tls:
                server.starttls(context=context)
                server.ehlo()

        if self.smtp_username and self.smtp_password:
            server.login(self.smtp_username, self.smtp_password)

        return server

    def _load_logo_bytes(self) -> bytes | None:
        if os.path.exists(LOGO_PATH):
            with open(LOGO_PATH, 'rb') as f:
                return f.read()
        return None

    def _send_raw(self, mime_msg) -> bool:
        self._validate_email_config()
        try:
            recipients = [address.strip() for address in mime_msg.get_all('to', []) if address]
            with self._open_smtp_connection() as server:
                server.send_message(mime_msg, from_addr=self.sender_email, to_addrs=recipients)
            LOGGER.info('Email enviado para %s', mime_msg['to'])
            return True
        except smtplib.SMTPException as e:
            LOGGER.exception('Erro SMTP ao enviar e-mail para %s', mime_msg.get('to', ''))
            raise RuntimeError(f'Falha SMTP ao enviar e-mail: {e}') from e
        except Exception as e:
            LOGGER.exception('Erro inesperado ao enviar e-mail para %s', mime_msg.get('to', ''))
            raise RuntimeError(f'Erro inesperado ao enviar e-mail: {e}') from e

    def _build_mime_com_logo(self, destino: str, assunto: str, html_body: str) -> MIMEMultipart:
        outer = MIMEMultipart('related')
        outer['to'] = destino
        outer['from'] = self.sender_email
        outer['subject'] = assunto

        alternative = MIMEMultipart('alternative')
        alternative.attach(MIMEText(html_body, 'html', 'utf-8'))
        outer.attach(alternative)

        logo_bytes = self._load_logo_bytes()
        if logo_bytes:
            img = MIMEImage(logo_bytes, _subtype='png')
            img.add_header('Content-ID', '<oraculo_logo>')
            img.add_header('Content-Disposition', 'inline', filename='logo.png')
            outer.attach(img)

        return outer

    def enviar_email(self, destino: str, assunto: str, mensagem: str) -> bool:
        if not self.sender_email:
            raise RuntimeError('EMAIL_REMETENTE não configurado.')

        msg = MIMEText(mensagem, 'html', 'utf-8')
        msg['to'] = destino
        msg['from'] = self.sender_email
        msg['subject'] = assunto
        return self._send_raw(msg)

    def enviar_boas_vindas(self, nome: str, email: str, whatsapp: str) -> bool:
        assunto = '🎉 Bem-vindo(a) ao Cripto Bolt!'
        data_cadastro = datetime.now().strftime('%d/%m/%Y às %H:%M')
        html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
</head>
<body style="margin:0;padding:0;background-color:#0d0d1a;font-family:'Segoe UI',Arial,sans-serif;color:#e0e0e0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0d0d1a;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:linear-gradient(160deg,#1a1a2e 0%,#16213e 100%);
                      border-radius:16px;overflow:hidden;
                      border:1px solid #00bcd4;">
          <tr>
            <td align="center" style="padding:36px 32px 20px;">
              <img src="cid:oraculo_logo" alt="Cripto Bolt"
                   width="110" height="110"
                   style="border-radius:50%;border:3px solid #00bcd4;display:block;margin:0 auto 20px;"/>
              <h1 style="margin:0;font-size:28px;font-weight:800;color:#ffffff;letter-spacing:0.5px;">
                <span style="color:#00bcd4;">✨</span> Bem-vindo(a) ao Cripto Bolt!
              </h1>
              <p style="margin:10px 0 0;font-size:15px;color:#b0aac8;">
                Sua jornada no universo de criptoativos começa agora.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 16px;">
              <p style="font-size:16px;line-height:1.6;color:#d0c8e8;">
                Olá, <strong style="color:#00bcd4;">{nome}</strong>! 👋<br/>
                Estamos muito felizes em tê-lo(a) como parte da nossa comunidade.
                O <strong>Cripto Bolt</strong> foi criado para ajudar você a
                navegar no mercado de criptoativos, DeFi e estratégias de trade
                com inteligência artificial.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#0f0f2a;border-radius:10px;
                            border:1px solid #00bcd4;overflow:hidden;">
                <tr>
                  <td colspan="2" style="padding:14px 20px;
                      background:linear-gradient(90deg,#004d40,#00695c);
                      font-size:13px;font-weight:700;
                      text-transform:uppercase;letter-spacing:1px;color:#e0f7fa;">
                    📋 Seus Dados de Cadastro
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 20px;color:#9ca3af;font-size:14px;width:40%;">Nome</td>
                  <td style="padding:10px 20px;color:#f3f4f6;font-size:14px;font-weight:600;">{nome}</td>
                </tr>
                <tr style="background:#13132b;">
                  <td style="padding:10px 20px;color:#9ca3af;font-size:14px;">E-mail</td>
                  <td style="padding:10px 20px;color:#f3f4f6;font-size:14px;font-weight:600;">{email}</td>
                </tr>
                <tr>
                  <td style="padding:10px 20px;color:#9ca3af;font-size:14px;">WhatsApp</td>
                  <td style="padding:10px 20px;color:#f3f4f6;font-size:14px;font-weight:600;">{whatsapp}</td>
                </tr>
                <tr style="background:#13132b;">
                  <td style="padding:10px 20px;color:#9ca3af;font-size:14px;">Cadastro em</td>
                  <td style="padding:10px 20px;color:#f3f4f6;font-size:14px;font-weight:600;">{data_cadastro}</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 24px;">
              <h2 style="margin:0 0 12px;font-size:18px;color:#00bcd4;">
                🤖 O que é o Cripto Bolt?
              </h2>
              <p style="margin:0;font-size:14px;line-height:1.7;color:#c4b8de;">
                O Cripto Bolt é uma plataforma de <strong>inteligência artificial</strong>
                especializada em criptoativos, protocolos DeFi, tokens, pools de liquidez
                e estratégias de Day Trade — tudo para ajudar você a tomar decisões
                mais conscientes no mercado cripto.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 32px;" align="center">
              <p style="font-size:14px;color:#b0aac8;margin:0 0 18px;">
                O próximo passo é verificar sua conta com o código que enviaremos em seguida.
                Após a verificação você terá acesso completo à plataforma.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background:#0a0a1a;border-top:1px solid #004d40;" align="center">
              <p style="margin:0;font-size:12px;color:#4b5563;">
                © {datetime.now().year} Cripto Bolt — Desenvolvido com ❤️<br/>
                Este e-mail foi enviado automaticamente. Por favor, não responda diretamente.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
        mime_msg = self._build_mime_com_logo(email, assunto, html)
        return self._send_raw(mime_msg)

    def enviar_notificacao_admin(self, nome: str, email: str, whatsapp: str) -> bool:
        admin_email = get_setting('EMAIL_ADMIN') or self.sender_email
        if not admin_email:
            raise RuntimeError('EMAIL_ADMIN ou EMAIL_REMETENTE não configurado.')

        agora = datetime.now()
        data_hora = agora.strftime('%d/%m/%Y às %H:%M:%S')
        assunto = f'📢 Novo Cadastro — {nome}'
        html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
</head>
<body style="margin:0;padding:0;background-color:#0d0d1a;font-family:'Segoe UI',Arial,sans-serif;color:#e0e0e0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0d0d1a;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:linear-gradient(160deg,#1a1a2e 0%,#16213e 100%);
                      border-radius:16px;overflow:hidden;
                      border:1px solid #00bcd4;">
          <tr>
            <td align="center" style="padding:36px 32px 20px;">
              <img src="cid:oraculo_logo" alt="Cripto Bolt"
                   width="110" height="110"
                   style="border-radius:50%;border:3px solid #00bcd4;display:block;margin:0 auto 20px;"/>
              <h1 style="margin:0;font-size:26px;font-weight:800;color:#ffffff;letter-spacing:0.5px;">
                <span style="color:#00bcd4;">📢</span> Novo Cliente Cadastrado
              </h1>
              <p style="margin:10px 0 0;font-size:15px;color:#b0aac8;">
                Painel Administrativo — Cripto Bolt
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 16px;">
              <p style="font-size:16px;line-height:1.6;color:#d0c8e8;">
                Um novo usuário acabou de se cadastrar na plataforma.
                Confira abaixo os dados do cadastro:
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#0f0f2a;border-radius:10px;
                            border:1px solid #00bcd4;overflow:hidden;">
                <tr>
                  <td colspan="2" style="padding:14px 20px;
                      background:linear-gradient(90deg,#004d40,#00695c);
                      font-size:13px;font-weight:700;
                      text-transform:uppercase;letter-spacing:1px;color:#e0f7fa;">
                    👤 Dados do Novo Cliente
                  </td>
                </tr>
                <tr>
                  <td style="padding:10px 20px;color:#9ca3af;font-size:14px;width:40%;">Nome</td>
                  <td style="padding:10px 20px;color:#f3f4f6;font-size:14px;font-weight:600;">{nome}</td>
                </tr>
                <tr style="background:#13132b;">
                  <td style="padding:10px 20px;color:#9ca3af;font-size:14px;">E-mail</td>
                  <td style="padding:10px 20px;color:#f3f4f6;font-size:14px;font-weight:600;">{email}</td>
                </tr>
                <tr>
                  <td style="padding:10px 20px;color:#9ca3af;font-size:14px;">WhatsApp</td>
                  <td style="padding:10px 20px;color:#f3f4f6;font-size:14px;font-weight:600;">{whatsapp}</td>
                </tr>
                <tr style="background:#13132b;">
                  <td style="padding:10px 20px;color:#9ca3af;font-size:14px;">Data/Hora</td>
                  <td style="padding:10px 20px;color:#f3f4f6;font-size:14px;font-weight:600;">{data_hora}</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background:#0a0a1a;border-top:1px solid #004d40;" align="center">
              <p style="margin:0;font-size:12px;color:#4b5563;">
                © {agora.year} Cripto Bolt — Notificação Administrativa<br/>
                Este e-mail foi enviado automaticamente. Por favor, não responda diretamente.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
        mime_msg = self._build_mime_com_logo(admin_email, assunto, html)
        return self._send_raw(mime_msg)

    def enviar_verificacao(self, nome: str, email: str, codigo: str) -> bool:
        assunto = '🔐 Código de Verificação — Cripto Bolt'
        primeiro_nome = nome.split()[0] if nome else nome
        html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
</head>
<body style="margin:0;padding:0;background-color:#0d0d1a;font-family:'Segoe UI',Arial,sans-serif;color:#e0e0e0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0d0d1a;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:linear-gradient(160deg,#1a1a2e 0%,#16213e 100%);
                      border-radius:16px;overflow:hidden;
                      border:1px solid #00bcd4;">
          <tr>
            <td align="center" style="padding:36px 32px 20px;">
              <img src="cid:oraculo_logo" alt="Cripto Bolt"
                   width="110" height="110"
                   style="border-radius:50%;border:3px solid #00bcd4;display:block;margin:0 auto 20px;"/>
              <h1 style="margin:0;font-size:26px;font-weight:800;color:#ffffff;letter-spacing:0.5px;">
                <span style="color:#00bcd4;">🔐</span> Verifique sua conta
              </h1>
              <p style="margin:10px 0 0;font-size:15px;color:#b0aac8;">
                Cripto Bolt — Ativação de Conta
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 20px;">
              <p style="font-size:16px;line-height:1.6;color:#d0c8e8;">
                Olá, <strong style="color:#00bcd4;">{primeiro_nome}</strong>! 👋<br/>
                Para ativar sua conta e ter acesso completo à plataforma,
                utilize o código de verificação abaixo:
              </p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:0 32px 28px;">
              <table cellpadding="0" cellspacing="0"
                     style="background:linear-gradient(135deg,#004d40,#00695c);
                            border-radius:12px;overflow:hidden;">
                <tr>
                  <td style="padding:10px 24px 4px;" align="center">
                    <p style="margin:0;font-size:12px;font-weight:700;letter-spacing:2px;
                               text-transform:uppercase;color:#b2dfdb;">
                      Seu Código de Verificação
                    </p>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding:8px 48px 16px;">
                    <span style="font-size:44px;font-weight:900;letter-spacing:12px;
                                 color:#ffffff;font-family:'Courier New',monospace;">
                      {codigo}
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 24px;">
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#1a103a;border-radius:10px;
                            border:1px solid #00695c;">
                <tr>
                  <td style="padding:16px 20px;">
                    <p style="margin:0 0 8px;font-size:14px;font-weight:700;color:#b2dfdb;">
                      ⚠️ Informações importantes:
                    </p>
                    <ul style="margin:0;padding-left:20px;font-size:14px;
                               line-height:1.8;color:#b0aac8;">
                      <li>Insira este código na tela de verificação do Cripto Bolt.</li>
                      <li>O código é <strong>válido para uso único</strong>.</li>
                      <li>Se você não solicitou este código, ignore este e-mail.</li>
                    </ul>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 32px;" align="center">
              <p style="font-size:13px;color:#6b7280;margin:0;">
                🔒 Por segurança, nunca compartilhe este código com ninguém.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background:#0a0a1a;border-top:1px solid #004d40;" align="center">
              <p style="margin:0;font-size:12px;color:#4b5563;">
                © {datetime.now().year} Cripto Bolt — Desenvolvido com ❤️<br/>
                Este e-mail foi enviado automaticamente. Por favor, não responda diretamente.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
        mime_msg = self._build_mime_com_logo(email, assunto, html)
        return self._send_raw(mime_msg)

    def _render_metric_cards(self, metricas: dict | None) -> str:
        if not metricas:
            return ""

        cards = []
        for titulo, valor in metricas.items():
            if valor in (None, "", [], {}):
                continue
            cards.append(
                f"""
                <td style="padding:8px;vertical-align:top;">
                  <div style="background:rgba(8,22,42,0.76);border:1px solid rgba(23,190,187,0.18);border-radius:16px;padding:14px 16px;height:100%;">
                    <div style="font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#7dd3fc;margin-bottom:6px;">{escape(str(titulo))}</div>
                    <div style="font-size:18px;font-weight:800;color:#f8fbff;">{escape(str(valor))}</div>
                  </div>
                </td>
                """
            )

        if not cards:
            return ""

        rows = []
        for idx in range(0, len(cards), 2):
            rows.append(f"<tr>{''.join(cards[idx:idx + 2])}</tr>")
        return f"<table width='100%' cellpadding='0' cellspacing='0' style='margin-top:18px;'>{''.join(rows)}</table>"

    def _render_bullets(self, itens: list[str] | None, titulo: str) -> str:
        if not itens:
            return ""
        bullets = ''.join(
            f"<li style='margin:0 0 10px;color:#dce9f7;line-height:1.65;'>{escape(str(item))}</li>"
            for item in itens if item
        )
        if not bullets:
            return ""
        return f"""
        <div style="margin-top:22px;padding:20px 22px;background:rgba(5,18,33,0.68);border:1px solid rgba(12,123,179,0.20);border-radius:18px;">
          <div style="font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:1.4px;color:#7dd3fc;margin-bottom:12px;">{escape(titulo)}</div>
          <ul style="padding-left:20px;margin:0;">{bullets}</ul>
        </div>
        """

    def _render_sources(self, fontes: list[str] | None) -> str:
        if not fontes:
            return ""
        links = ''.join(
            f"<li style='margin:0 0 8px;'><a href='{escape(url)}' style='color:#7dd3fc;text-decoration:none;'>{escape(url)}</a></li>"
            for url in fontes if url
        )
        if not links:
            return ""
        return f"""
        <div style="margin-top:18px;padding:18px 20px;background:rgba(255,255,255,0.03);border-radius:16px;border:1px solid rgba(255,255,255,0.08);">
          <div style="font-size:13px;font-weight:700;color:#a5f3fc;margin-bottom:10px;">Fontes e referências</div>
          <ul style="padding-left:20px;margin:0;">{links}</ul>
        </div>
        """

    def _build_modern_email(self, destino: str, assunto: str, *, eyebrow: str, titulo: str, subtitulo: str, conteudo_html: str, accent: str = '#00bcd4') -> MIMEMultipart:
        ano = datetime.now().year
        html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
</head>
<body style="margin:0;padding:0;background:#06111f;font-family:'Segoe UI',Arial,sans-serif;color:#dbe7f3;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:radial-gradient(circle at top,#11315b 0%,#06111f 52%,#030712 100%);">
    <tr>
      <td align="center" style="padding:34px 14px;">
        <table width="680" cellpadding="0" cellspacing="0" style="max-width:680px;background:linear-gradient(160deg,rgba(7,18,35,0.98) 0%,rgba(9,27,46,0.96) 55%,rgba(5,15,28,0.99) 100%);border-radius:28px;overflow:hidden;border:1px solid rgba(125,211,252,0.14);box-shadow:0 24px 60px rgba(0,0,0,0.32);">
          <tr>
            <td style="padding:34px 36px 22px;background:linear-gradient(135deg,rgba(12,123,179,0.22),rgba(23,190,187,0.16));border-bottom:1px solid rgba(125,211,252,0.12);">
              <div style="font-size:12px;text-transform:uppercase;letter-spacing:1.8px;color:{accent};font-weight:800;margin-bottom:14px;">{escape(eyebrow)}</div>
              <img src="cid:oraculo_logo" alt="Cripto Bolt" width="86" height="86" style="display:block;border-radius:24px;border:2px solid rgba(125,211,252,0.24);background:rgba(255,255,255,0.04);padding:10px;"/>
              <h1 style="margin:18px 0 10px;font-size:30px;line-height:1.14;color:#f8fbff;font-weight:900;letter-spacing:-0.03em;">{escape(titulo)}</h1>
              <p style="margin:0;font-size:15px;line-height:1.7;color:#b8d4e8;">{escape(subtitulo)}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 36px 34px;">{conteudo_html}</td>
          </tr>
          <tr>
            <td style="padding:20px 36px;background:#040b14;border-top:1px solid rgba(125,211,252,0.10);">
              <p style="margin:0;font-size:12px;line-height:1.7;color:#6e86a1;">© {ano} Cripto Bolt. Mensagem automática enviada por Hostinger SMTP. Não responda diretamente este e-mail.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
        return self._build_mime_com_logo(destino, assunto, html)

    def enviar_relatorio_chat(
        self,
        destino: str,
        *,
        nome: str,
        tipo_relatorio: str,
        titulo: str,
        resumo: str,
        recomendacao: str = '',
        score: int | None = None,
        metricas: dict | None = None,
        insights: list[str] | None = None,
        fontes: list[str] | None = None,
    ) -> bool:
        tipos = {
            'token': ('Relatório de Token', 'Leitura operacional de ativo com inteligência do Cripto Bolt.'),
            'protocolo': ('Relatório de Protocolo DeFi', 'Panorama estrutural de protocolo, adoção e risco de execução.'),
            'pool': ('Relatório de Pool / LP', 'Resumo técnico de yield, liquidez, IL e eficiência de capital.'),
            'pesquisa': ('Pesquisa de Mercado', 'Resumo objetivo do que foi solicitado no chat e principais implicações.'),
        }
        eyebrow, subtitulo = tipos.get(tipo_relatorio, tipos['pesquisa'])
        metricas_envio = dict(metricas or {})
        if score is not None:
            metricas_envio = {'Score': f'{score}/100', **metricas_envio}
        if recomendacao:
            metricas_envio['Recomendação'] = recomendacao

        conteudo_html = f"""
        <p style="margin:0 0 16px;font-size:16px;line-height:1.75;color:#dce9f7;">Olá, <strong style="color:#a5f3fc;">{escape(nome or 'investidor')}</strong>. O chat do Cripto Bolt gerou um novo relatório solicitado por você.</p>
        <div style="padding:22px 24px;background:linear-gradient(145deg,rgba(12,123,179,0.12),rgba(23,190,187,0.08));border:1px solid rgba(125,211,252,0.15);border-radius:22px;">
          <div style="font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:1.4px;color:#7dd3fc;margin-bottom:12px;">Resumo executivo</div>
          <div style="font-size:15px;line-height:1.78;color:#f3f8fc;white-space:pre-line;">{escape(resumo)}</div>
        </div>
        {self._render_metric_cards(metricas_envio)}
        {self._render_bullets(insights, 'Pontos de atenção')}
        {self._render_sources(fontes)}
        """
        assunto = f'Cripto Bolt - {titulo}'
        mime_msg = self._build_modern_email(
            destino,
            assunto,
            eyebrow=eyebrow,
            titulo=titulo,
            subtitulo=subtitulo,
            conteudo_html=conteudo_html,
        )
        return self._send_raw(mime_msg)

    def enviar_resumo_diario_atividades(
        self,
        destino: str,
        *,
        resumo: str,
        atividades: list[str] | None = None,
        destaques: dict | None = None,
    ) -> bool:
        data_ref = datetime.now().strftime('%d/%m/%Y')
        conteudo_html = f"""
        <p style="margin:0 0 16px;font-size:16px;line-height:1.75;color:#dce9f7;">Resumo consolidado das atividades do dia no Cripto Bolt em <strong style="color:#a5f3fc;">{data_ref}</strong>.</p>
        <div style="padding:22px 24px;background:linear-gradient(145deg,rgba(255,159,28,0.10),rgba(12,123,179,0.10));border:1px solid rgba(255,159,28,0.18);border-radius:22px;">
          <div style="font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:1.4px;color:#ffbf69;margin-bottom:12px;">Fechamento do dia</div>
          <div style="font-size:15px;line-height:1.78;color:#f3f8fc;white-space:pre-line;">{escape(resumo)}</div>
        </div>
        {self._render_metric_cards(destaques)}
        {self._render_bullets(atividades, 'Atividades de hoje')}
        """
        mime_msg = self._build_modern_email(
            destino,
            'Cripto Bolt - Atividades de hoje',
            eyebrow='Resumo Diário',
            titulo='Atividades de hoje',
            subtitulo='Digest automático diário com panorama operacional e principais ocorrências.',
            conteudo_html=conteudo_html,
            accent='#ffbf69',
        )
        return self._send_raw(mime_msg)

    def disparar_resumo_diario(self, destino: str | None = None) -> bool:
        destino_final = destino or get_setting('EMAIL_DESTINOS_RESUMO_DIARIO') or get_setting('EMAIL_ADMIN') or self.sender_email
        if not destino_final:
            raise RuntimeError('EMAIL_DESTINOS_RESUMO_DIARIO, EMAIL_ADMIN ou EMAIL_REMETENTE não configurado.')

        atividades = [
            'Monitoramento diário de inteligência e relatórios automáticos finalizado.',
            'Consolidação de pesquisas, leituras operacionais e alertas do Cripto Bolt executada.',
            'Revisão de riscos, contexto de execução e pontos pendentes preparada para o próximo ciclo.',
        ]
        destaques = {
            'Janela de envio': datetime.now().strftime('%H:%M'),
            'Canal': 'Resumo automático via Hostinger SMTP',
            'Status': 'Concluído',
        }
        resumo = (
            'O Cripto Bolt finalizou o fechamento operacional do dia. '
            'Este resumo reúne as principais atividades processadas, reforça os pontos de risco observados e mantém o time alinhado para a próxima janela de análise.'
        )
        return self.enviar_resumo_diario_atividades(
            destino_final,
            resumo=resumo,
            atividades=atividades,
            destaques=destaques,
        )


def _job_resumo_diario_email():
    try:
        Notificador().disparar_resumo_diario()
        LOGGER.info('Resumo diário enviado com sucesso.')
    except Exception as exc:
        LOGGER.error('Falha ao enviar resumo diário: %s', exc)


def iniciar_agendamento_resumo_diario():
    global _email_scheduler

    if _email_scheduler is not None and _email_scheduler.running:
        return _email_scheduler

    timezone = get_setting('DAILY_SUMMARY_TIMEZONE', default='America/Sao_Paulo')
    hour = int(get_setting('DAILY_SUMMARY_HOUR', default='20'))
    minute = int(get_setting('DAILY_SUMMARY_MINUTE', default='30'))

    _email_scheduler = BackgroundScheduler(timezone=timezone)
    _email_scheduler.add_job(
        _job_resumo_diario_email,
        CronTrigger(hour=hour, minute=minute),
        id='email_resumo_diario',
        replace_existing=True,
    )
    _email_scheduler.start()
    LOGGER.info('Scheduler de resumo diário iniciado para %02d:%02d (%s).', hour, minute, timezone)
    return _email_scheduler


def get_scheduler_resumo_diario_status() -> dict:
    if _email_scheduler is None or not _email_scheduler.running:
        return {'running': False, 'jobs': []}

    jobs = []
    for job in _email_scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'next_run': str(job.next_run_time) if job.next_run_time else 'N/A',
            'trigger': str(job.trigger),
        })
    return {'running': True, 'jobs': jobs}
