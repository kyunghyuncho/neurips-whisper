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


# Whitelist of allowed URL patterns
# Only URLs matching these patterns are allowed in messages
# This prevents spam, phishing, and unwanted external links
URL_WHITELIST_PATTERNS = [
    # Google Maps links (useful for conference venue/locations)
    r"https?://(www\.)?google\.[a-z]+/maps.*",
    r"https?://maps\.app\.goo\.gl/.*",
    
    # Academic research links (core to conference discussions)
    r"https?://(www\.)?arxiv\.org/(abs|pdf)/.*",  # arXiv papers
    r"https?://(www\.)?openreview\.net/.*",       # OpenReview papers
    
    # Conference official website
    r"https?://(www\.)?neurips\.cc/.*"
]


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
    Check if a URL matches the whitelist patterns.
    
    This prevents users from posting arbitrary external links while
    allowing useful conference-related URLs (maps, papers, official site).
    
    Whitelist approach (allow known-good) is more secure than blacklist
    (block known-bad) because it's impossible to list all malicious sites.
    
    Args:
        url: URL to validate (should start with http:// or https://)
        
    Returns:
        True if URL matches any whitelist pattern, False otherwise
        
    Examples:
        >>> is_valid_url("https://arxiv.org/abs/2301.12345")
        True
        >>> is_valid_url("https://malicious-site.com")
        False
    """
    # Check each allowed pattern
    for pattern in URL_WHITELIST_PATTERNS:
        # re.match checks if URL starts with pattern
        # Returns a Match object if successful, None otherwise
        if re.match(pattern, url):
            return True
    
    # URL doesn't match any whitelist pattern
    return False
