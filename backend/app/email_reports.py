"""Monthly production summary email report."""

from .timeutil import utcnow as _utcnow
from datetime import datetime, timedelta
from typing import Optional
import html
import statistics
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import io
import logging

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .analytics import FleetKPICalculator

logger = logging.getLogger(__name__)

# Email config from environment
import os
SMTP_HOST = os.getenv("MEMAR_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("MEMAR_SMTP_PORT", "587"))
SMTP_USER = os.getenv("MEMAR_SMTP_USER", "")
SMTP_PASSWORD = os.getenv("MEMAR_SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("MEMAR_SMTP_FROM", SMTP_USER)


class MonthlyReportGenerator:
    """Generate and email monthly production summary."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.analytics = FleetKPICalculator(db)

    async def generate_html_report(self, year: int, month: int) -> str:
        """Generate monthly summary as HTML (for email body)."""
        from .models_db import JobLog
        from .config import get_config

        # Date range
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)

        # Fetch jobs for month from the JobLog telemetry table.
        jobs = (await self.db.execute(
            select(JobLog).where(JobLog.created_at >= start, JobLog.created_at < end)
        )).scalars().all()

        total_jobs = len(jobs)
        successful_jobs = len([j for j in jobs if j.status == "completed"])
        failed_jobs = len([j for j in jobs if j.status == "failed"])
        uptime_pct = (successful_jobs / total_jobs * 100) if total_jobs > 0 else 0

        oee_values = [j.oee for j in jobs if j.oee is not None]
        avg_oee = statistics.mean(oee_values) if oee_values else 0

        # Device identity from config (the single source of truth).
        device_stats = []
        for device in get_config().printers:
            if not device.enabled:
                continue
            device_jobs = [j for j in jobs if j.device_id == device.id]
            if device_jobs:
                device_oee_values = [j.oee for j in device_jobs if j.oee is not None]
                device_oee = statistics.mean(device_oee_values) if device_oee_values else 0
                device_stats.append({
                    "name": html.escape(device.name),
                    "status": "—",
                    "jobs": len(device_jobs),
                    "oee": device_oee,
                })

        # HTML template
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                h1 {{ color: #1f2937; border-bottom: 2px solid #3b82f6; padding-bottom: 10px; }}
                h2 {{ color: #374151; margin-top: 20px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
                th {{ background-color: #3b82f6; color: white; padding: 10px; text-align: left; }}
                td {{ padding: 10px; border-bottom: 1px solid #e5e7eb; }}
                tr:nth-child(even) {{ background-color: #f9fafb; }}
                .metric {{ font-size: 24px; font-weight: bold; }}
                .positive {{ color: #10b981; }}
                .negative {{ color: #ef4444; }}
                .metric-card {{ display: inline-block; margin: 10px; padding: 15px; background: #f3f4f6; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <h1>MEMAR Monthly Production Report</h1>
            <p><strong>{start.strftime('%B %Y')}</strong></p>

            <h2>Summary Metrics</h2>
            <div class="metric-card">
                <div>Total Jobs</div>
                <div class="metric">{total_jobs}</div>
            </div>
            <div class="metric-card">
                <div>Successful</div>
                <div class="metric positive">{successful_jobs}</div>
            </div>
            <div class="metric-card">
                <div>Failed</div>
                <div class="metric negative">{failed_jobs}</div>
            </div>
            <div class="metric-card">
                <div>Success Rate</div>
                <div class="metric">{uptime_pct:.1f}%</div>
            </div>
            <div class="metric-card">
                <div>Average OEE</div>
                <div class="metric">{avg_oee * 100:.1f}%</div>
            </div>

            <h2>Equipment Performance</h2>
            <table>
                <thead>
                    <tr>
                        <th>Equipment</th>
                        <th>Status</th>
                        <th>Jobs Completed</th>
                        <th>Average OEE</th>
                    </tr>
                </thead>
                <tbody>
        """

        for device in device_stats:
            html += f"""
                    <tr>
                        <td>{device['name']}</td>
                        <td>{device['status']}</td>
                        <td>{device['jobs']}</td>
                        <td>{device['oee'] * 100:.1f}%</td>
                    </tr>
            """

        html += """
                </tbody>
            </table>

            <h2>Notes</h2>
            <p>This is an automated report. For details or questions, contact your MEMAR administrator.</p>

            <hr>
            <p style="font-size: 12px; color: #9ca3af;">
                Generated by MEMAR Fleet Monitoring • {timestamp}
            </p>
        </body>
        </html>
        """.format(timestamp=_utcnow().isoformat())

        return html

    async def send_email(
        self,
        recipient_email: str,
        year: int,
        month: int,
        subject_suffix: str = ""
    ) -> bool:
        """Generate HTML report and email it."""

        if not SMTP_USER or not SMTP_PASSWORD:
            logger.warning("SMTP not configured; skipping email")
            return False

        try:
            html_report = await self.generate_html_report(year, month)

            msg = MIMEMultipart('alternative')
            msg['From'] = SMTP_FROM
            msg['To'] = recipient_email
            msg['Subject'] = f"MEMAR Monthly Report — {datetime(year, month, 1).strftime('%B %Y')} {subject_suffix}".strip()

            # Plain text fallback
            text = f"""
            MEMAR Monthly Production Report
            {datetime(year, month, 1).strftime('%B %Y')}

            Please view this email in HTML format for best experience.
            Or log in to MEMAR for detailed analytics.
            """

            msg.attach(MIMEText(text, 'plain'))
            msg.attach(MIMEText(html_report, 'html'))

            async with aiosmtplib.SMTP(hostname=SMTP_HOST, port=SMTP_PORT, start_tls=True) as smtp:
                await smtp.login(SMTP_USER, SMTP_PASSWORD)
                await smtp.send_message(msg)

            logger.info(f"Email sent to {recipient_email}")
            return True

        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False

    async def send_bulk_monthly_reports(self, year: int, month: int, recipient_list: list[str]) -> dict:
        """Send monthly reports to multiple recipients."""
        results = {
            "success": 0,
            "failed": 0,
            "errors": []
        }

        for email in recipient_list:
            try:
                success = await self.send_email(email, year, month)
                if success:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(f"Failed to send to {email}")
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"Error sending to {email}: {str(e)}")

        return results
