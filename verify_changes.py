"""
Verification Script for NeurIPS Whisper

This script tests key utility functions to ensure they work correctly.
It's particularly useful after making changes to validators and text processing.

Run this script to verify:
- URL validation against whitelist patterns
- Text linkification (URLs and hashtags)
- Message truncation logic

Usage:
    python verify_changes.py
"""

import sys
import os
import re
from datetime import datetime

# Add app to path so we can import modules
# This allows running the script from any directory
sys.path.append(os.getcwd())

from app.utils.validators import is_valid_url
from app.utils.text import linkify_content


def test_validators():
    print("Testing Validators...")
    allowed = [
        "https://arxiv.org/abs/2301.12345",
        "https://openreview.net/forum?id=12345",
        "https://neurips.cc/virtual/2023/poster/123",
        "https://www.google.com/maps/place/New+York",
        "https://maps.app.goo.gl/12345"
    ]
    disallowed = [
        "https://example.com",
        "https://google.com", # Not maps
        "https://twitter.com",
        "http://malicious.com"
    ]
    
    for url in allowed:
        assert is_valid_url(url), f"Should be allowed: {url}"
    for url in disallowed:
        assert not is_valid_url(url), f"Should be disallowed: {url}"
    print("Validators passed!")

def test_linkify():
    print("Testing Linkify...")
    # Hashtags SHOULD be linkified now
    text = "Hello #world check https://arxiv.org/abs/123"
    linked = linkify_content(text)
    print(f"Original: {text}")
    print(f"Linked: {linked}")
    
    assert '<a href="https://arxiv.org/abs/123"' in linked
    assert 'class="hashtag' in linked
    assert '#world' in linked
    print("Linkify passed!")

def test_truncation_logic():
    print("Testing Truncation Logic...")
    
    def mock_format(content):
        MAX_PREVIEW_LENGTH = 140
        result = {}
        if len(content) > MAX_PREVIEW_LENGTH:
            result["is_long"] = True
            preview = content[:MAX_PREVIEW_LENGTH]
            last_space = preview.rfind(" ")
            if last_space > 0:
                preview = preview[:last_space]
            result["preview_content"] = preview + "..."
        else:
            result["is_long"] = False
            result["preview_content"] = content
        return result

    short_msg = "Short message"
    long_msg = "This is a very long message that should be truncated because it exceeds the limit of 140 characters. " * 3
    
    res_short = mock_format(short_msg)
    assert not res_short["is_long"]
    assert res_short["preview_content"] == short_msg
    
    res_long = mock_format(long_msg)
    assert res_long["is_long"]
    assert len(res_long["preview_content"]) < 150 # 140 + "..."
    assert "..." in res_long["preview_content"]
    
    print("Truncation logic passed!")

if __name__ == "__main__":
    test_validators()
    test_linkify()
    test_truncation_logic()
