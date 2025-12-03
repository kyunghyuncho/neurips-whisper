"""
Security Service - VirusTotal Integration

This module provides functionality to check URLs against the VirusTotal API
to detect malicious or suspicious links.
"""

import requests
import base64
import asyncio
from app.config import settings
import logging

logger = logging.getLogger(__name__)

async def check_url_safety(url: str) -> bool:
    """
    Check if a URL is safe using VirusTotal API.
    
    Args:
        url: The URL to check
        
    Returns:
        True if the URL is safe or unknown, False if it's malicious or suspicious.
        If the API key is not configured or the API call fails, it defaults to True (fail open).
    """
    if not settings.VIRUSTOTAL_API_KEY:
        logger.warning("VirusTotal API key not configured. Skipping URL check.")
        return True

    def _check_sync():
        try:
            # VirusTotal requires the URL to be base64 encoded without padding
            url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")
            
            api_url = f"https://www.virustotal.com/api/v3/urls/{url_id}"
            headers = {
                "x-apikey": settings.VIRUSTOTAL_API_KEY
            }
            
            response = requests.get(api_url, headers=headers)
            
            if response.status_code == 404:
                # URL not found in VirusTotal database, assume safe for now
                return True
            
            if response.status_code != 200:
                logger.error(f"VirusTotal API error: {response.status_code}")
                return True
            
            data = response.json()
            attributes = data.get("data", {}).get("attributes", {})
            stats = attributes.get("last_analysis_stats", {})
            
            malicious = stats.get("malicious", 0)
            suspicious = stats.get("suspicious", 0)
            
            if malicious > 0 or suspicious > 0:
                logger.info(f"Blocked suspicious URL: {url} (Malicious: {malicious}, Suspicious: {suspicious})")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error checking URL safety: {e}")
            return True

    # Run blocking request in a separate thread to avoid blocking the event loop
    return await asyncio.to_thread(_check_sync)
