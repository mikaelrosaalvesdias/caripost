"""
Notifier — WhatsApp (Evolution API) + Email (SMTP).

Config lives in Settings (preferred) with env fallback:
  WhatsApp / Evolution API:
    notify.evolution.url       (e.g. https://evolution.n8nmikael.com.br)  | env EVOLUTION_URL
    notify.evolution.apiKey    (encrypted)                                | env EVOLUTION_API_KEY
    notify.evolution.instance  (instance name)                            | env EVOLUTION_INSTANCE
  Email / SMTP:
    notify.smtp.host/port/user/pass(encrypted)/from/fromName/tls         | env SMTP_*
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

logger = logging.getLogger("caripost.notifier")


def _setting(key: str, *, decrypt_value: bool = False) -> str:
    try:
        from ..db import settings_get
        row = settings_get(key=key)
    except Exception:
        return ""
    value = str((row or {}).get("value") or "").strip()
    if value and decrypt_value:
        try:
            from ..security.encryption import decrypt
            return (decrypt(value) or value).strip()
        except Exception:
            return value
    return value


# ── Config ───────────────────────────────────────────────────────────────────

def evolution_config() -> Dict[str, str]:
    return {
        "url": (_setting("notify.evolution.url") or os.environ.get("EVOLUTION_URL") or "").strip().rstrip("/"),
        "api_key": (_setting("notify.evolution.apiKey", decrypt_value=True) or os.environ.get("EVOLUTION_API_KEY") or "").strip(),
        "instance": (_setting("notify.evolution.instance") or os.environ.get("EVOLUTION_INSTANCE") or "").strip(),
    }


def smtp_config() -> Dict[str, Any]:
    return {
        "host": (_setting("notify.smtp.host") or os.environ.get("SMTP_HOST") or "").strip(),
        "port": int(_setting("notify.smtp.port") or os.environ.get("SMTP_PORT") or "587"),
        "user": (_setting("notify.smtp.user") or os.environ.get("SMTP_USER") or "").strip(),
        "password": (_setting("notify.smtp.pass", decrypt_value=True) or os.environ.get("SMTP_PASS") or "").strip(),
        "from": (_setting("notify.smtp.from") or os.environ.get("SMTP_FROM") or "noreply@caripost.n8nmikael.com.br").strip(),
        "from_name": (_setting("notify.smtp.fromName") or os.environ.get("SMTP_FROM_NAME") or "Caripost").strip(),
        "tls": (_setting("notify.smtp.tls") or os.environ.get("SMTP_STARTTLS") or "1") not in ("0", "false", "no"),
    }


def config_status() -> Dict[str, Any]:
    evo = evolution_config()
    smtp = smtp_config()
    return {
        "whatsapp": {"url": evo["url"], "instance": evo["instance"], "configured": bool(evo["url"] and evo["api_key"] and evo["instance"])},
        "smtp": {"host": smtp["host"], "from": smtp["from"], "configured": bool(smtp["host"])},
    }


# ── WhatsApp (Evolution API) ───────────────────────────────────────────────────

def normalize_number(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    # Default to Brazil country code when a local number is given.
    if len(digits) <= 11 and not digits.startswith("55"):
        digits = "55" + digits
    return digits


async def send_whatsapp(number: str, text: str) -> Dict[str, Any]:
    cfg = evolution_config()
    if not (cfg["url"] and cfg["api_key"] and cfg["instance"]):
        return {"ok": False, "error": "WhatsApp (Evolution API) não configurado em Settings → Notificações."}
    num = normalize_number(number)
    if not num:
        return {"ok": False, "error": "Número inválido."}
    try:
        import httpx
    except ImportError:
        return {"ok": False, "error": "httpx não instalado."}
    url = f"{cfg['url']}/message/sendText/{cfg['instance']}"
    headers = {"apikey": cfg["api_key"], "content-type": "application/json"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        # Evolution API v2 payload
        res = await client.post(url, headers=headers, json={"number": num, "text": text})
        if res.status_code >= 400:
            # legacy v1 fallback
            res = await client.post(url, headers=headers, json={"number": num, "textMessage": {"text": text}})
        ok = res.status_code < 400
        try:
            data = res.json()
        except Exception:
            data = {"text": res.text[:300]}
    if not ok:
        logger.error("Evolution sendText failed %s: %s", res.status_code, data)
        return {"ok": False, "error": f"Evolution HTTP {res.status_code}", "detail": data}
    return {"ok": True, "data": data}


# ── Email (SMTP) ───────────────────────────────────────────────────────────────

def send_email_sync(to: str, subject: str, html: str, text: Optional[str] = None) -> Dict[str, Any]:
    cfg = smtp_config()
    if not cfg["host"]:
        return {"ok": False, "error": "SMTP não configurado em Settings → Notificações."}
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg['from_name']} <{cfg['from']}>"
    msg["To"] = to
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            if cfg["tls"]:
                server.starttls()
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from"], [to], msg.as_string())
        return {"ok": True}
    except Exception as exc:
        logger.error("SMTP send failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def send_email(to: str, subject: str, html: str, text: Optional[str] = None) -> Dict[str, Any]:
    import asyncio
    return await asyncio.to_thread(send_email_sync, to, subject, html, text)


# ── High-level: notify approval recipients ────────────────────────────────────

async def notify(*, company_id: str, channel: str, recipient: str, subject: str, message: str, trigger: str = "", html: Optional[str] = None) -> Dict[str, Any]:
    """Send one notification and log it. channel = 'whatsapp' | 'email'."""
    if channel == "whatsapp":
        result = await send_whatsapp(recipient, message)
    elif channel == "email":
        result = await send_email(recipient, subject, html or f"<p>{message}</p>", text=message)
    else:
        result = {"ok": False, "error": f"Canal desconhecido: {channel}"}
    try:
        from ..db_companies import notifications_log_create
        notifications_log_create({
            "company_id": company_id, "channel": channel, "trigger": trigger,
            "recipient": recipient, "status": "sent" if result.get("ok") else "failed",
            "detail": result.get("error") or "",
        })
    except Exception:
        pass
    return result
