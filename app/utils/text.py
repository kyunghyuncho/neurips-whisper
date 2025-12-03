"""
Text Processing Utilities

This module provides functions for processing message content:
1. linkify_content: Convert URLs and hashtags to clickable HTML links
2. extract_terms: Extract significant words for search/caching

These utilities help make the message feed interactive and searchable.
"""

import re


def linkify_content(text: str) -> str:
    """
    Convert URLs and hashtags in text to clickable HTML links.
    
    This makes the message feed more interactive by:
    - Making URLs clickable (open in new tab)
    - Making hashtags clickable (filter feed by tag)
    
    Args:
        text: Raw message content that may contain URLs and #hashtags
        
    Returns:
        HTML string with <a> tags for URLs and hashtags
        
    Example:
        >>> linkify_content("Check out https://arxiv.org and #machinelearning")
        'Check out <a href="https://arxiv.org"...>https://arxiv.org</a> and <a href="#"...>#machinelearning</a>'
    
    Security notes:
    - rel="noopener noreferrer": Prevents tabnabbing attacks
    - onclick="event.stopPropagation()": Prevents event bubbling issues
    """
    def replace(match):
        """Helper function called for each regex match."""
        url = match.group(1)  # Captured URL (if present)
        hashtag = match.group(2)  # Captured hashtag (if present)
        
        if url:
            # Create clickable external link
            # - target="_blank": Opens in new tab
            # - rel="noopener noreferrer": Security best practice
            # - onclick="event.stopPropagation()": Prevents parent click handlers
            
            # Shorten URL for display (e.g. https://example.com/very/long/path -> example.com/very...)
            display_url = url
            try:
                # Remove protocol
                short_url = re.sub(r'^https?://', '', url)
                # Truncate if too long
                if len(short_url) > 30:
                    display_url = short_url[:27] + "..."
                else:
                    display_url = short_url
            except:
                pass
                
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="text-blue-500 hover:underline" onclick="event.stopPropagation()">{display_url}</a>'
        
        if hashtag:
            # Create clickable hashtag filter link
            # - href="#": Prevents navigation
            # - toggleHashtag(): JavaScript function to filter by tag
            # - return false: Prevents default anchor behavior
            tag = hashtag[1:]  # Remove the # symbol
            return f'<a href="#" onclick="toggleHashtag(\'{tag}\'); return false;" class="hashtag text-blue-500 hover:underline">{hashtag}</a>'
        
        # Fallback (shouldn't happen with our regex)
        return match.group(0)

    # Regex pattern to match URLs and hashtags
    # (https?://\S+): Capture http/https URLs (group 1)
    # (#\w+): Capture hashtags (group 2)
    # The | means "or" - match either pattern
    pattern = r'(https?://\S+)|(#\w+)'
    
    # Replace all matches using the replace function
    return re.sub(pattern, replace, text)


def calculate_weighted_length(text: str) -> int:
    """
    Calculate the weighted length of text where URLs count as 1 character.
    
    Args:
        text: The text to measure
        
    Returns:
        The weighted length
    """
    # Regex to find URLs
    url_pattern = r'https?://\S+'
    
    # Remove all URLs
    text_without_urls = re.sub(url_pattern, '', text)
    
    # Count number of URLs
    urls = re.findall(url_pattern, text)
    num_urls = len(urls)
    
    # Weighted length = length of text without URLs + 1 char per URL
    return len(text_without_urls) + num_urls


def extract_terms(text: str) -> set[str]:
    """
    Extract significant terms from text for indexing and search.
    
    This helps build a searchable cache of message content by:
    - Filtering out common stop words (the, is, are, etc.)
    - Removing URLs and hashtags (processed separately)
    - Keeping only words longer than 2 characters
    - Converting to lowercase for case-insensitive matching
    
    Args:
        text: Message content to extract terms from
        
    Returns:
        Set of unique significant terms (lowercase)
        
    Example:
        >>> extract_terms("I am presenting new research on #ML at NeurIPS")
        {'presenting', 'research', 'neurips'}
        # Note: 'am', 'new', 'at' are stop words; '#ML' is a hashtag
    """
    # Comprehensive list of English stop words to filter out
    # These are common words that don't add meaning for search
    STOP_WORDS = {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", 
        "it", "for", "not", "on", "with", "he", "as", "you", "do", "at", 
        "this", "but", "his", "by", "from", "they", "we", "say", "her", 
        "she", "or", "an", "will", "my", "one", "all", "would", "there", 
        "their", "what", "so", "up", "out", "if", "about", "who", "get", 
        "which", "go", "me", "when", "make", "can", "like", "time", "no", 
        "just", "him", "know", "take", "people", "into", "year", "your", 
        "good", "some", "could", "them", "see", "other", "than", "then", 
        "now", "look", "only", "come", "its", "over", "think", "also", 
        "back", "after", "use", "two", "how", "our", "work", "first", 
        "well", "way", "even", "new", "want", "because", "any", "these", 
        "give", "day", "most", "us", "is", "are", "was", "were", "has", "had"
    }
    
    # Remove URLs and hashtags first (they're processed separately)
    # This prevents URLs/hashtags from being split into separate terms
    text = re.sub(r'(https?://\S+)|(#\w+)', '', text)
    
    # Extract all words (alphanumeric sequences)
    # \b: Word boundary (ensures we get complete words)
    # \w+: One or more word characters (letters, digits, underscore)
    words = re.findall(r'\b\w+\b', text.lower())
    
    # Filter words to keep only significant terms
    valid_terms = set()
    for word in words:
        # Keep words that are:
        # 1. Longer than 2 characters (filters out "is", "at", etc.)
        # 2. Not in the stop words list
        if len(word) > 2 and word not in STOP_WORDS:
            valid_terms.add(word)
    
    return valid_terms
