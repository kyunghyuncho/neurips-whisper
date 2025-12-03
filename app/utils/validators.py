"""
Input Validation Utilities

This module provides validation functions for user input:
1. is_institutional_email: Ensures users have institutional/company emails
2. is_valid_url: Whitelist-based URL validation for security

These validators help maintain quality and security in the conference app.
"""

import re


# List of free email provider domains to reject
# We only want institutional/company emails for conference attendees
# This list includes popular providers from US, China, Europe, and Russia
FREE_EMAIL_DOMAINS = {
    # US/Global providers
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", 
    "live.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me",
    
    # Chinese providers
    "163.com", "126.com", "qq.com", "foxmail.com", "sina.com", "sohu.com", "yeah.net",
    
    # European/Russian providers
    "gmx.de", "gmx.net", "web.de", "mail.ru", "yandex.ru", 
    "libero.it", "virgilio.it", "laposte.net"
}


def is_institutional_email(email: str) -> bool:
    """
    Check if an email address is from an institution (not a free provider).
    
    This helps ensure users are actual conference attendees with
    institutional or company affiliations, rather than random users
    signing up with free email accounts.
    
    Args:
        email: Email address to validate (e.g., "user@university.edu")
        
    Returns:
        True if email is institutional, False if it's a free provider
        
    Examples:
        >>> is_institutional_email("student@mit.edu")
        True
        >>> is_institutional_email("user@gmail.com")
        False
    """
    # Extract domain from email (everything after @)
    # Convert to lowercase for case-insensitive matching
    domain = email.split("@")[-1].lower()
    
    # Reject if domain is in the free provider list
    return domain not in FREE_EMAIL_DOMAINS

def is_valid_url(url: str) -> bool:
    """
    Check if a string looks like a valid URL.
    
    We now allow any URL but will check it against VirusTotal for safety.
    
    Args:
        url: URL to validate
        
    Returns:
        True if it looks like a URL, False otherwise
    """
    # Basic regex for URL validation
    # Matches http:// or https:// followed by non-whitespace characters
    pattern = r"https?://\S+"
    return bool(re.match(pattern, url))
