"""
Email Service for Magic Link Authentication

This module handles sending authentication emails using the Resend API.
Resend is a modern email service with a simple API for transactional emails.

The magic link email contains a one-time login URL that authenticates
the user when clicked, providing a passwordless authentication experience.
"""

import resend
from app.config import settings
import logging


# Set up logging for debugging email sending issues
logger = logging.getLogger(__name__)

# Configure Resend API with our API key
# This must be set before making any API calls
resend.api_key = settings.RESEND_API_KEY


def send_magic_link(to_email: str, link: str):
    """
    Send a magic link authentication email to the specified address.
    
    This creates and sends an email with a clickable login link.
    The link contains a JWT token that will log the user in when accessed.
    
    Args:
        to_email: Recipient's email address
        link: Full URL for the magic link (includes token as query parameter)
              Format: https://domain.com/auth/verify?token=<jwt>
              
    Raises:
        Exception: If email sending fails (network error, invalid API key, etc.)
        
    Note:
        Errors are logged and re-raised. The calling code should handle failures
        gracefully (e.g., show user a friendly error message).
    """
    try:
        # Build email parameters per Resend API spec
        params = {
            "from": settings.FROM_EMAIL,  # Must be verified in Resend dashboard
            "to": [to_email],  # List of recipients
            "subject": "NeurIPS Whisper Login",
            # HTML email body with clickable link
            # The link is shown both as text and as an href for accessibility
            "html": f'<strong>Click here to login:</strong> <a href="{link}">{link}</a>',
        }

        # Send email via Resend API
        # This is a synchronous API call
        email = resend.Emails.send(params)
        
        # Log success for debugging/monitoring
        logger.info(f"Email sent to {to_email}: {email}")
        
    except Exception as e:
        # Log the error with details for debugging
        logger.error(f"Error sending email to {to_email}: {e}")
        
        # Re-raise to let calling code handle it
        # This allows the route handler to return appropriate error response
        raise e
