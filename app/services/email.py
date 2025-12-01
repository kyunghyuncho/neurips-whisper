import resend
from app.config import settings
import logging

logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY

def send_magic_link(to_email: str, link: str):
    try:
        params = {
            "from": settings.FROM_EMAIL,
            "to": [to_email],
            "subject": "NeurIPS Whisper Login",
            "html": f'<strong>Click here to login:</strong> <a href="{link}">{link}</a>',
        }

        email = resend.Emails.send(params)
        logger.info(f"Email sent to {to_email}: {email}")
    except Exception as e:
        logger.error(f"Error sending email to {to_email}: {e}")
        raise e
