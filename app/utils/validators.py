import re

# Global Free Provider List
FREE_EMAIL_DOMAINS = {
    # US/Global
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me",
    # China
    "163.com", "126.com", "qq.com", "foxmail.com", "sina.com", "sohu.com", "yeah.net",
    # Europe/Russia
    "gmx.de", "gmx.net", "web.de", "mail.ru", "yandex.ru", "libero.it", "virgilio.it", "laposte.net"
}

# URL Whitelist Regex
URL_WHITELIST_PATTERNS = [
    r"https?://(www\.)?google\.[a-z]+/maps.*",
    r"https?://maps\.app\.goo\.gl/.*",
    r"https?://(www\.)?arxiv\.org/(abs|pdf)/.*",
    r"https?://(www\.)?openreview\.net/.*",
    r"https?://(www\.)?neurips\.cc/.*"
]

def is_institutional_email(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    return domain not in FREE_EMAIL_DOMAINS

def is_valid_url(url: str) -> bool:
    for pattern in URL_WHITELIST_PATTERNS:
        if re.match(pattern, url):
            return True
    return False
