"""
Scheduled tasks using APScheduler (AsyncIOScheduler).

Started during FastAPI app startup (app.on_event("startup")).
All tasks are async and use the same event loop as FastAPI.

Schedule overview:
  - 06:00 daily   : collect trending data
  - 08:00 Monday  : generate briefings for all creators
  - 03:00 daily   : scrape stats for all creators
  - 04:00 every 2d: DMCA scan for all creators
  - every 5 min   : process scheduled publications
  - every 10 min  : process cross-promotions
  - 02:00 Sunday  : check all platform logins
  - 10:00 1st/mo  : generate monthly financial reports
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            _scheduler = AsyncIOScheduler(timezone="UTC")
        except ImportError:
            logger.warning("APScheduler not installed — scheduled tasks disabled")
            return None
    return _scheduler


# ─────────────────────────────────────────────────────────────────────────────
# Task functions
# ─────────────────────────────────────────────────────────────────────────────

async def task_collect_trends():
    """Cron: collect trending data daily at 06:00 UTC."""
    logger.info("[CRON] Starting trend collection...")
    try:
        from ..services.trend_collector import collect_trending_data
        result = await collect_trending_data()
        logger.info("[CRON] Trend collection done: %s records", result.get("record_count", 0))
    except Exception as exc:
        logger.error("[CRON] Trend collection failed: %s", exc)


async def task_generate_briefings():
    """Cron: generate weekly briefings for all active creators (Monday 08:00 UTC).
    First collects reference channel data to enrich the briefings.
    """
    logger.info("[CRON] Starting reference channel collection before briefings...")
    try:
        from ..services.trend_collector import collect_all_reference_channels
        ch_result = await collect_all_reference_channels()
        logger.info("[CRON] Channel collection done: %d videos from %d creators",
                    ch_result["total_videos"], ch_result["creators_processed"])
    except Exception as exc:
        logger.warning("[CRON] Channel collection failed (briefings will use cached data): %s", exc)

    logger.info("[CRON] Starting briefing generation...")
    try:
        from ..services.trend_briefing import generate_briefings_for_all_creators
        result = await generate_briefings_for_all_creators()
        logger.info("[CRON] Briefings: %d generated, %d failed", result["generated"], result["failed"])
    except Exception as exc:
        logger.error("[CRON] Briefing generation failed: %s", exc)


async def task_scrape_stats():
    """Cron: scrape stats from all active creators (03:00 UTC daily)."""
    logger.info("[CRON] Starting stats scraping for all creators...")
    try:
        from ..db_agency import creator_list
        from ..routers.creators import _scrape_stats_task
        creators = creator_list(status="active")
        for creator in creators:
            try:
                await _scrape_stats_task(creator["creator_id"])
            except Exception as exc:
                logger.error("[CRON] Stats scrape failed for %s: %s", creator["creator_id"], exc)
        logger.info("[CRON] Stats scraping complete for %d creators", len(creators))
    except Exception as exc:
        logger.error("[CRON] Stats scraping failed: %s", exc)


async def task_dmca_scan():
    """Cron: DMCA scan for all active creators (04:00 UTC every 2 days)."""
    logger.info("[CRON] Starting DMCA scan...")
    try:
        from ..db_agency import creator_list
        from ..services.dmca_scanner import scan_creator
        creators = creator_list(status="active")
        for creator in creators:
            try:
                result = await scan_creator(creator["creator_id"])
                found = result.get("infringements_found", 0)
                if found:
                    logger.info("[CRON] DMCA: %d infringements found for %s", found, creator["name"])
                await asyncio.sleep(10)  # rate limit between creators
            except Exception as exc:
                logger.error("[CRON] DMCA scan failed for %s: %s", creator["creator_id"], exc)
        logger.info("[CRON] DMCA scan complete for %d creators", len(creators))
    except Exception as exc:
        logger.error("[CRON] DMCA scan failed: %s", exc)


async def task_process_scheduled_publications():
    """Cron: check calendar and publish due entries (every 5 minutes)."""
    try:
        from ..services.calendar_scheduler import process_scheduled_publications
        result = await process_scheduled_publications()
        if result.get("triggered", 0) > 0:
            logger.info("[CRON] Triggered %d scheduled publications", result["triggered"])
    except Exception as exc:
        logger.error("[CRON] Scheduled publications check failed: %s", exc)


async def task_process_scheduled_social_posts():
    """Cron: publish due social posts through the Social Integration Layer."""
    try:
        from ..social.service import process_due_social_posts
        result = await process_due_social_posts()
        if result.get("triggered", 0) > 0:
            logger.info("[CRON] Triggered %d scheduled social posts", result["triggered"])
    except Exception as exc:
        logger.error("[CRON] Scheduled social posts check failed: %s", exc)


async def task_process_cross_promotions():
    """Cron: post cross-promotions for published entries (every 10 minutes)."""
    try:
        from ..services.cross_promoter import process_pending_cross_promotions
        result = await process_pending_cross_promotions()
        if result.get("processed", 0) > 0:
            logger.info("[CRON] Processed %d cross-promotions", result["processed"])
    except Exception as exc:
        logger.error("[CRON] Cross-promotions failed: %s", exc)


async def task_check_platform_logins():
    """Cron: verify all platform cookies are still valid (Sunday 02:00 UTC)."""
    logger.info("[CRON] Checking platform login sessions...")
    try:
        from ..db_agency import creator_list, get_conn
        from ..publishers.registry import get_driver
        from ..db_agency import platform_account_get_with_cookies, platform_account_update_login_check
        from ..security.encryption import decrypt

        creators = creator_list(status="active")
        for creator in creators:
            cid = creator["creator_id"]
            with get_conn() as conn:
                platforms = [
                    r["platform"]
                    for r in conn.execute(
                        "SELECT platform FROM platform_accounts WHERE creator_id=? AND status='active'", (cid,)
                    ).fetchall()
                ]
            for platform in platforms:
                DriverClass = get_driver(platform)
                if not DriverClass:
                    continue
                account = platform_account_get_with_cookies(cid, platform)
                cookies_json = decrypt(account.get("cookies_json") or "") if account else None
                try:
                    async with DriverClass(cookies_json=cookies_json, headless=True) as driver:
                        is_logged = await driver.check_login()
                    status = "active" if is_logged else "expired"
                    platform_account_update_login_check(cid, platform, status)
                    if not is_logged:
                        logger.warning("[CRON] Login expired for %s/%s", creator["name"], platform)
                except Exception as exc:
                    logger.error("[CRON] Login check failed for %s/%s: %s", creator["name"], platform, exc)
                await asyncio.sleep(3)
        logger.info("[CRON] Login check complete for %d creators", len(creators))
    except Exception as exc:
        logger.error("[CRON] Login check failed: %s", exc)


async def task_agency_tick():
    """Agência automática: fila de artes, agendamento, publicação, lembretes (a cada 3 min)."""
    try:
        from ..services.agency import tick
        st = await tick()
        if any(st.values()):
            logger.info("[CRON] agency tick %s", st)
    except Exception as exc:
        logger.warning("[CRON] agency tick falhou: %s", exc)


async def task_agency_monthly():
    """Agência automática: no dia configurado gera o calendário do mês seguinte e avisa no WhatsApp."""
    try:
        from ..services.agency import monthly_job
        done = await monthly_job()
        if done:
            logger.info("[CRON] agency monthly gerou: %s", done)
    except Exception as exc:
        logger.warning("[CRON] agency monthly falhou: %s", exc)


async def task_monthly_reports():
    """Cron: generate and send monthly financial reports (1st of month, 10:00 UTC)."""
    logger.info("[CRON] Generating monthly financial reports...")
    try:
        from ..db_agency import creator_list, creator_get
        from ..services.financial_calculator import get_monthly_report
        from ..services.email_sender import send_monthly_report_email
        from datetime import timedelta

        # Previous month
        today = datetime.now(timezone.utc)
        first_this_month = today.replace(day=1)
        last_month = first_this_month - timedelta(days=1)
        period = last_month.strftime("%Y-%m")

        creators = creator_list(status="active")
        sent = 0
        for creator in creators:
            try:
                report = get_monthly_report(creator["creator_id"], period)
                if report.get("total_gross", 0) > 0:
                    result = await send_monthly_report_email(creator, report)
                    if result.get("success"):
                        sent += 1
            except Exception as exc:
                logger.error("[CRON] Monthly report failed for %s: %s", creator["creator_id"], exc)

        logger.info("[CRON] Monthly reports sent to %d creators for %s", sent, period)
    except Exception as exc:
        logger.error("[CRON] Monthly reports task failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler setup
# ─────────────────────────────────────────────────────────────────────────────

def setup_scheduler() -> None:
    """Register all cron jobs and start the scheduler."""
    scheduler = get_scheduler()
    if scheduler is None:
        logger.warning("APScheduler unavailable — cron tasks not scheduled")
        return

    if scheduler.running:
        return  # already started

    scheduler.add_job(
        task_collect_trends,
        trigger="cron",
        hour=6, minute=0,
        id="trends_collect",
        replace_existing=True,
    )
    scheduler.add_job(
        task_generate_briefings,
        trigger="cron",
        day_of_week="mon", hour=8, minute=0,
        id="trends_briefing",
        replace_existing=True,
    )
    scheduler.add_job(
        task_scrape_stats,
        trigger="cron",
        hour=3, minute=0,
        id="scrape_stats",
        replace_existing=True,
    )
    scheduler.add_job(
        task_dmca_scan,
        trigger="cron",
        hour=4, minute=0,
        day="*/2",
        id="dmca_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        task_process_scheduled_publications,
        trigger="interval",
        minutes=5,
        id="publish_scheduled",
        replace_existing=True,
    )
    scheduler.add_job(
        task_process_scheduled_social_posts,
        trigger="interval",
        minutes=3,
        id="social_publish_scheduled",
        replace_existing=True,
    )
    scheduler.add_job(
        task_process_cross_promotions,
        trigger="interval",
        minutes=10,
        id="cross_promote",
        replace_existing=True,
    )
    scheduler.add_job(
        task_check_platform_logins,
        trigger="cron",
        day_of_week="sun", hour=2, minute=0,
        id="login_check",
        replace_existing=True,
    )
    scheduler.add_job(
        task_monthly_reports,
        trigger="cron",
        day=1, hour=10, minute=0,
        id="monthly_report",
        replace_existing=True,
    )

    scheduler.add_job(
        task_agency_tick,
        trigger="interval",
        minutes=3,
        id="agency_tick",
        replace_existing=True,
    )
    scheduler.add_job(
        task_agency_monthly,
        trigger="cron",
        hour=12, minute=0,                  # 09:00 de Brasília; o dia (padrão 20) é checado por empresa
        id="agency_monthly",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("APScheduler started with %d jobs", len(scheduler.get_jobs()))


def shutdown_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")
