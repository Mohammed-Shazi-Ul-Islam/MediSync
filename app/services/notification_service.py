"""
app/services/notification_service.py

Module 04 — Async Notification Pipeline: SMS (Twilio) + Email (SMTP) delivery.

Design principles:
  1. Every send method is wrapped in try/except — a notification failure is
     NEVER allowed to propagate up and crash the Celery pipeline. Triage and
     routing results are always preserved regardless of notification outcome.

  2. Graceful degradation — if Twilio or SMTP credentials are not configured,
     the methods log a warning and return False instead of raising. This lets
     developers run the full pipeline locally without a Twilio account.

  3. The service is instantiated once as a module-level singleton (notification_service)
     following the same pattern as triage_service and hybrid_router.

  4. HTML email templates are inline strings — no template engine dependency.
     A production version would use Jinja2, but we keep dependencies minimal.

Usage from Celery tasks:
    from app.services.notification_service import notification_service
    notification_service.notify_patient_triaged(report, patient)
    notification_service.notify_doctor_alert(doctor, report)
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from app.models.doctor import Doctor
    from app.models.intake import SymptomReport
    from app.models.patient import Patient

logger = logging.getLogger(__name__)
settings = get_settings()


# ── HTML Email Templates ───────────────────────────────────────────────────────

def _report_received_html(patient_name: str, report_id: str, ref_short: str) -> str:
    return f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
      <div style="background: #1a73e8; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="color: white; margin: 0;">🏥 MediSync</h1>
        <p style="color: #e8f0fe; margin: 4px 0 0 0;">Intelligent Patient Triage System</p>
      </div>
      <div style="background: #f8f9fa; padding: 24px; border-radius: 0 0 8px 8px;">
        <p>Dear <strong>{patient_name}</strong>,</p>
        <p>We have received your symptom report and our AI triage system is processing it now.</p>
        <div style="background: white; border-left: 4px solid #1a73e8; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
          <p style="margin: 0;"><strong>Reference Number:</strong> <code>{ref_short}</code></p>
          <p style="margin: 4px 0 0 0; font-size: 12px; color: #666;">Full ID: {report_id}</p>
        </div>
        <p>You will receive another notification once a specialist has been assigned to your case.</p>
        <p style="color: #d32f2f; font-weight: bold;">⚠️ If you are experiencing a medical emergency, please call emergency services immediately.</p>
        <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
        <p style="font-size: 12px; color: #999;">This is an automated message from MediSync. Do not reply to this email.</p>
      </div>
    </body></html>
    """


def _triaged_html(
    patient_name: str,
    urgency: str,
    specialist: str,
    report_id: str,
    reasoning: str,
) -> str:
    urgency_colors = {"critical": "#d32f2f", "moderate": "#f57c00", "routine": "#388e3c"}
    color = urgency_colors.get(urgency.lower(), "#1a73e8")
    return f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
      <div style="background: #1a73e8; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="color: white; margin: 0;">🏥 MediSync — Triage Result</h1>
      </div>
      <div style="background: #f8f9fa; padding: 24px; border-radius: 0 0 8px 8px;">
        <p>Dear <strong>{patient_name}</strong>,</p>
        <p>Your symptom report has been reviewed by our AI triage system. Here is the result:</p>
        <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden;">
          <tr style="background: {color}; color: white;">
            <td style="padding: 12px 16px; font-weight: bold;">Urgency Level</td>
            <td style="padding: 12px 16px; text-transform: uppercase; font-weight: bold;">{urgency}</td>
          </tr>
          <tr>
            <td style="padding: 12px 16px; border-bottom: 1px solid #eee; color: #666;">Recommended Specialist</td>
            <td style="padding: 12px 16px; border-bottom: 1px solid #eee;">{specialist.replace("_", " ").title()}</td>
          </tr>
          <tr>
            <td style="padding: 12px 16px; color: #666; vertical-align: top;">Assessment</td>
            <td style="padding: 12px 16px;">{reasoning}</td>
          </tr>
        </table>
        <p style="margin-top: 20px;">A doctor has been notified and will review your case shortly.</p>
        <p style="color: #d32f2f; font-weight: bold;">⚠️ If your symptoms worsen suddenly, call emergency services immediately.</p>
        <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
        <p style="font-size: 12px; color: #999;">Reference: {report_id}</p>
      </div>
    </body></html>
    """


def _doctor_alert_html(
    doctor_name: str,
    patient_name: str,
    urgency: str,
    specialist: str,
    raw_text: str,
    report_id: str,
    escalation_count: int,
) -> str:
    urgency_colors = {"critical": "#d32f2f", "moderate": "#f57c00", "routine": "#388e3c"}
    color = urgency_colors.get(urgency.lower(), "#1a73e8")
    escalation_badge = ""
    if escalation_count > 0:
        escalation_badge = f'<span style="background: #f57c00; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">ESCALATION #{escalation_count}</span>'
    return f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: auto;">
      <div style="background: {color}; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="color: white; margin: 0;">🚨 MediSync — New Case Alert {escalation_badge}</h1>
      </div>
      <div style="background: #f8f9fa; padding: 24px; border-radius: 0 0 8px 8px;">
        <p>Dear <strong>Dr. {doctor_name}</strong>,</p>
        <p>A new patient case has been routed to you and requires your attention.</p>
        <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; margin: 16px 0;">
          <tr style="background: {color}; color: white;">
            <td colspan="2" style="padding: 10px 16px; font-weight: bold;">
              URGENCY: {urgency.upper()} | SPECIALTY: {specialist.replace("_", " ").upper()}
            </td>
          </tr>
          <tr>
            <td style="padding: 10px 16px; border-bottom: 1px solid #eee; width: 35%; color: #666;">Patient</td>
            <td style="padding: 10px 16px; border-bottom: 1px solid #eee;">{patient_name}</td>
          </tr>
          <tr>
            <td style="padding: 10px 16px; color: #666; vertical-align: top;">Symptoms</td>
            <td style="padding: 10px 16px; font-style: italic;">"{raw_text[:500]}{'...' if len(raw_text) > 500 else ''}"</td>
          </tr>
        </table>
        <p>Please log in to the MediSync dashboard to accept or reject this case.</p>
        <p style="font-size: 12px; color: #999;">Report ID: {report_id}</p>
      </div>
    </body></html>
    """


# ── Notification Service ───────────────────────────────────────────────────────

class NotificationService:
    """
    Centralised notification delivery for Module 04.

    All public methods return bool (True = delivered, False = skipped/failed).
    All exceptions are caught internally — callers are never affected by
    delivery failures.
    """

    # ── Low-Level Sends ────────────────────────────────────────────────────────

    def send_sms(self, to: str, body: str) -> bool:
        """
        Send an SMS via Twilio.

        Returns True on success, False if credentials missing or call fails.
        """
        if not all([settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_phone_number]):
            logger.warning("[NOTIFY] Twilio credentials not configured — SMS skipped")
            return False

        try:
            from twilio.rest import Client  # type: ignore[import]
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            message = client.messages.create(
                body=body,
                from_=settings.twilio_phone_number,
                to=to,
            )
            logger.info(f"[NOTIFY] SMS sent to {to} — SID: {message.sid}")
            return True
        except Exception as exc:
            logger.error(f"[NOTIFY] SMS delivery failed to {to}: {exc}")
            return False

    def send_email(self, to: str, subject: str, body: str, html_body: str | None = None) -> bool:
        """
        Send an email via SMTP (TLS).

        Returns True on success, False if credentials missing or call fails.
        Falls back to plain text if html_body is None.
        """
        if not all([settings.smtp_user, settings.smtp_password]):
            logger.warning("[NOTIFY] SMTP credentials not configured — email skipped")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.smtp_from_email
            msg["To"] = to

            msg.attach(MIMEText(body, "plain"))
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from_email, to, msg.as_string())

            logger.info(f"[NOTIFY] Email sent to {to}: '{subject}'")
            return True
        except Exception as exc:
            logger.error(f"[NOTIFY] Email delivery failed to {to}: {exc}")
            return False

    # ── High-Level Patient Notifications ──────────────────────────────────────

    def notify_patient_received(self, report: SymptomReport, patient: Patient) -> None:
        """
        Notify the patient that their symptom report was received.
        Sends SMS + email (whichever channels are configured).
        """
        report_id = str(report.id)
        ref_short = report_id[:8].upper()

        sms_body = (
            f"[MediSync] Hi {patient.full_name}, we received your symptom report "
            f"(Ref: {ref_short}). Our AI is processing it. "
            f"If this is an emergency, call emergency services immediately."
        )

        contact_phone = getattr(patient, "phone", None)
        contact_email = getattr(patient, "email", None)

        if contact_phone:
            self.send_sms(contact_phone, sms_body)

        if contact_email:
            self.send_email(
                to=contact_email,
                subject="[MediSync] Your symptom report has been received",
                body=sms_body,
                html_body=_report_received_html(patient.full_name, report_id, ref_short),
            )

    def notify_patient_triaged(
        self,
        report: SymptomReport,
        patient: Patient,
        urgency: str,
        specialist: str,
        reasoning: str = "",
    ) -> None:
        """
        Notify patient of their triage result and the assigned specialist type.
        """
        report_id = str(report.id)
        specialist_display = specialist.replace("_", " ").title()

        sms_body = (
            f"[MediSync] Hi {patient.full_name}, your triage result is ready. "
            f"Urgency: {urgency.upper()}. Specialist: {specialist_display}. "
            f"A doctor has been notified. Ref: {report_id[:8].upper()}"
        )

        contact_phone = getattr(patient, "phone", None)
        contact_email = getattr(patient, "email", None)

        if contact_phone:
            self.send_sms(contact_phone, sms_body)

        if contact_email:
            self.send_email(
                to=contact_email,
                subject=f"[MediSync] Triage Result — Urgency: {urgency.upper()}",
                body=sms_body,
                html_body=_triaged_html(
                    patient.full_name, urgency, specialist, report_id, reasoning
                ),
            )

    def notify_patient_case_accepted(self, report: SymptomReport, patient: Patient, doctor: Doctor) -> None:
        """Notify patient that a doctor has accepted their case."""
        sms_body = (
            f"[MediSync] Good news, {patient.full_name}! "
            f"Dr. {doctor.full_name} ({doctor.specialty.replace('_', ' ').title()}) "
            f"has accepted your case. They will be in touch shortly. "
            f"Ref: {str(report.id)[:8].upper()}"
        )
        if patient.phone:
            self.send_sms(patient.phone, sms_body)
        if patient.email:
            self.send_email(
                to=patient.email,
                subject="[MediSync] A doctor has accepted your case",
                body=sms_body,
            )

    # ── High-Level Doctor Notifications ───────────────────────────────────────

    def notify_doctor_alert(
        self,
        doctor: Doctor,
        report: SymptomReport,
        patient: Patient,
        escalation_count: int = 0,
    ) -> None:
        """
        Alert a doctor about a new case assignment via SMS + email.
        escalation_count=0 means first offer; >0 means this is an escalated case.
        """
        report_id = str(report.id)
        urgency = report.urgency_level or "unknown"
        specialist = report.specialist_recommendation or "general_practitioner"

        sms_prefix = f"[ESCALATION #{escalation_count}] " if escalation_count > 0 else ""
        sms_body = (
            f"[MediSync] {sms_prefix}Dr. {doctor.full_name}, new case assigned. "
            f"Patient: {patient.full_name} | Urgency: {urgency.upper()} | "
            f"Specialty: {specialist.replace('_', ' ').title()}. "
            f"Login to accept/reject. Ref: {report_id[:8].upper()}"
        )

        if doctor.phone:
            self.send_sms(doctor.phone, sms_body)

        if doctor.email:
            self.send_email(
                to=doctor.email,
                subject=f"[MediSync] {'⚠️ ESCALATED — ' if escalation_count > 0 else ''}New Case: {urgency.upper()} | {patient.full_name}",
                body=sms_body,
                html_body=_doctor_alert_html(
                    doctor.full_name,
                    patient.full_name,
                    urgency,
                    specialist,
                    report.raw_text,
                    report_id,
                    escalation_count,
                ),
            )

    def notify_admin_max_escalations(self, report_id: str, escalation_count: int) -> None:
        """
        Send an admin alert when no doctor accepts a case after max escalations.
        Currently logs a critical-level message. In production, this would page an on-call admin.
        """
        logger.critical(
            f"[ESCALATION] ⛔ Report {report_id} exhausted all {escalation_count} escalation "
            f"attempts with no doctor accepting. Manual intervention required."
        )
        # If admin SMTP is configured, send email to smtp_from_email as a placeholder admin address
        if settings.smtp_user:
            self.send_email(
                to=settings.smtp_from_email,
                subject=f"[MediSync CRITICAL] Case {report_id[:8].upper()} unaccepted after {escalation_count} escalations",
                body=(
                    f"ALERT: Symptom report {report_id} has not been accepted by any doctor "
                    f"after {escalation_count} escalation attempts. "
                    f"Please review the case immediately in the admin dashboard."
                ),
            )


# ── Singleton ──────────────────────────────────────────────────────────────────
notification_service = NotificationService()
