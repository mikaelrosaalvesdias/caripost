"""
Email sender: sends emails via SMTP.
Configure with environment variables:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@caripost.n8nmikael.com.br")
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Caripost")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _load_template(name: str) -> str:
    path = TEMPLATES_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _render_template(template_str: str, variables: Dict[str, str]) -> str:
    result = template_str
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result


async def send_email(
    to: Union[str, List[str]],
    subject: str,
    text_body: Optional[str] = None,
    html_body: Optional[str] = None,
    from_name: Optional[str] = None,
    template_name: Optional[str] = None,
    template_vars: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Send an email. Returns {"success": bool, "error": str|None}.
    If SMTP is not configured, logs a warning and returns mock success.
    """
    if not SMTP_HOST:
        logger.warning("SMTP not configured (SMTP_HOST not set). Email not sent to: %s", to)
        return {"success": True, "warning": "SMTP not configured — email not actually sent"}

    if isinstance(to, str):
        to = [to]

    if template_name and not html_body:
        tmpl = _load_template(template_name)
        if tmpl:
            html_body = _render_template(tmpl, template_vars or {})

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            _send_sync, to, subject, text_body, html_body, from_name,
        )
        return {"success": True}
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _send_sync(
    to: List[str],
    subject: str,
    text_body: Optional[str],
    html_body: Optional[str],
    from_name: Optional[str],
) -> None:
    msg = MIMEMultipart("alternative")
    display_name = from_name or SMTP_FROM_NAME
    msg["From"] = f"{display_name} <{SMTP_FROM}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    elif text_body and not html_body:
        pass  # already attached

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.ehlo()
        if SMTP_PORT in (587, 465) or os.environ.get("SMTP_STARTTLS", "1") == "1":
            server.starttls()
        if SMTP_USER and SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_FROM, to, msg.as_string())


async def send_briefing_email(creator: Dict, briefing: Dict) -> Dict[str, Any]:
    """Send a trend briefing email to a creator."""
    to = creator.get("email", "")
    if not to:
        return {"success": False, "error": "No email address"}

    name = creator.get("name", "Criador")
    content = briefing.get("content", {})
    market_summary = content.get("market_summary", "")
    suggestions = content.get("suggestions", [])

    # Build simple HTML if template not found
    sug_html = ""
    for s in suggestions[:5]:
        potential_emoji = {"low": "🟡", "medium": "🟠", "high": "🟢", "viral": "🔥"}.get(
            s.get("view_potential", "medium"), "🟠"
        )
        tags_html = " ".join(f'<span style="background:#ff1744;color:#fff;padding:2px 6px;border-radius:3px;font-size:11px">{t}</span>' for t in s.get("tags", [])[:8])
        sug_html += f"""
        <div style="background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:12px">
          <h3 style="color:#ff1744;margin:0 0 8px">{potential_emoji} {s.get("title", "")}</h3>
          <p style="color:#ccc;margin:0 0 8px">{s.get("concept", "")}</p>
          <p style="color:#888;font-size:12px;margin:0 0 8px"><strong>Por que está em alta:</strong> {s.get("why_trending", "")}</p>
          <div>{tags_html}</div>
        </div>"""

    avoid_list = "".join(f"<li>{a}</li>" for a in content.get("avoid", []))

    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#111;color:#fff;padding:24px;max-width:640px;margin:auto">
<div style="text-align:center;margin-bottom:24px">
  <h1 style="color:#ff1744">Caripost</h1>
  <p style="color:#888">Briefing Semanal de Tendências</p>
</div>
<p>Olá, <strong>{name}</strong>!</p>
<div style="background:#1a1a1a;border-left:4px solid #ff1744;padding:16px;margin:16px 0">
  <strong>Resumo do Mercado:</strong><br>{market_summary}
</div>
<h2>🎬 Sugestões de Produção</h2>
{sug_html}
<h2 style="color:#ff4444">⛔ Evitar Esta Semana</h2>
<ul style="color:#ccc">{avoid_list}</ul>
<hr style="border-color:#333;margin:24px 0">
<p style="color:#555;font-size:12px;text-align:center">
  Caripost — Conteúdo automatizado com IA<br>
  <a href="https://caripost.n8nmikael.com.br" style="color:#ff1744">caripost.n8nmikael.com.br</a>
</p>
</body></html>"""

    return await send_email(
        to=to,
        subject=f"📊 Briefing Semanal de Tendências — {name}",
        html_body=html_body,
        from_name="Caripost",
    )


async def send_monthly_report_email(creator: Dict, report: Dict) -> Dict[str, Any]:
    """Send a monthly financial report to a creator."""
    to = creator.get("email", "")
    if not to:
        return {"success": False, "error": "No email address"}

    name = creator.get("name", "Criador")
    month = report.get("month", "")
    gross = report.get("total_gross", 0)
    payout = report.get("total_creator_payout", 0)
    views = report.get("total_views", 0)

    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#111;color:#fff;padding:24px;max-width:600px;margin:auto">
<h1 style="color:#ff1744">Caripost</h1>
<h2>Relatório Mensal — {month}</h2>
<p>Olá, <strong>{name}</strong>! Aqui está o resumo financeiro do mês:</p>
<table style="width:100%;border-collapse:collapse;margin:16px 0">
  <tr style="background:#1a1a1a">
    <td style="padding:10px;border:1px solid #333">Receita Bruta</td>
    <td style="padding:10px;border:1px solid #333;color:#4CAF50">R$ {gross:.2f}</td>
  </tr>
  <tr>
    <td style="padding:10px;border:1px solid #333">Seu Repasse (após comissão)</td>
    <td style="padding:10px;border:1px solid #333;color:#ff1744"><strong>R$ {payout:.2f}</strong></td>
  </tr>
  <tr style="background:#1a1a1a">
    <td style="padding:10px;border:1px solid #333">Views no Período</td>
    <td style="padding:10px;border:1px solid #333">{views:,}</td>
  </tr>
</table>
<p style="color:#555;font-size:12px">Caripost · <a href="https://caripost.n8nmikael.com.br" style="color:#ff1744">caripost.n8nmikael.com.br</a></p>
</body></html>"""

    return await send_email(
        to=to,
        subject=f"💰 Relatório Financeiro {month} — {name}",
        html_body=html_body,
    )
