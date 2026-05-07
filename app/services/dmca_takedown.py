"""
DMCA takedown: generates and sends takedown notices via email.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..db_agency import dmca_list, dmca_update_status, creator_get
from .email_sender import send_email

logger = logging.getLogger(__name__)

DMCA_NOTICE_TEMPLATE = """\
DMCA TAKEDOWN NOTICE

Date: {date}
To: abuse@{infringing_site}, webmaster@{infringing_site}

Dear Sir or Madam,

This letter serves as a formal notification under the provisions of the Digital Millennium Copyright Act (DMCA), 17 U.S.C. § 512(c).

IDENTIFICATION OF COPYRIGHTED WORK:
The copyrighted content being infringed is an adult video owned and created by {creator_name}.
Original URL(s): {original_url}

IDENTIFICATION OF INFRINGING MATERIAL:
The infringing content is located at the following URL:
{infringing_url}

STATEMENT OF AUTHORITY:
I am the authorized representative of the copyright owner of the material described above. The information in this notification is accurate, and I declare under penalty of perjury that I am authorized to act on behalf of the copyright owner.

I request that you immediately remove or disable access to the infringing material listed above.

Please send confirmation of compliance to: {contact_email}

Respectfully,
{creator_name}
MetaPorn Agency — Content Protection Division
Date: {date}
"""


async def send_takedown(infringement_id: str, contact_email: str = "dmca@metaporn.com.br") -> Dict[str, Any]:
    """Generate and send a DMCA takedown notice."""
    # Load infringement
    infringements = dmca_list()
    inf = next((i for i in infringements if i["infringement_id"] == infringement_id), None)
    if not inf:
        return {"success": False, "error": "infringement_not_found"}

    creator = creator_get(inf["creator_id"])
    if not creator:
        return {"success": False, "error": "creator_not_found"}

    creator_name = creator.get("name", "Content Creator")
    infringing_site = inf.get("infringing_site", "unknown")
    infringing_url = inf.get("infringing_url", "")
    original_url = inf.get("original_url", "")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    notice_body = DMCA_NOTICE_TEMPLATE.format(
        date=now_str,
        creator_name=creator_name,
        infringing_site=infringing_site,
        infringing_url=infringing_url,
        original_url=original_url,
        contact_email=contact_email,
    )

    # Send to abuse@ and webmaster@
    recipients = [
        f"abuse@{infringing_site}",
        f"webmaster@{infringing_site}",
    ]

    try:
        result = await send_email(
            to=recipients,
            subject=f"DMCA Takedown Notice — {infringing_site}",
            text_body=notice_body,
            from_name="MetaPorn DMCA Team",
        )
        if result.get("success"):
            dmca_update_status(infringement_id, "takedown_sent")
            return {"success": True, "recipients": recipients}
        else:
            dmca_update_status(infringement_id, "failed", {"notes": result.get("error", "Email failed")})
            return {"success": False, "error": result.get("error")}
    except Exception as exc:
        logger.error("DMCA takedown failed for %s: %s", infringement_id, exc)
        dmca_update_status(infringement_id, "failed", {"notes": str(exc)})
        return {"success": False, "error": str(exc)}
