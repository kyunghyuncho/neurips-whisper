import re

def linkify_content(text: str) -> str:
    """
    Replaces URLs and hashtags in text with HTML links.
    """
    def replace(match):
        url = match.group(1)
        hashtag = match.group(2)
        if url:
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="text-blue-500 hover:underline" onclick="event.stopPropagation()">{url}</a>'
        if hashtag:
            tag = hashtag[1:]
            return f'<a href="#" onclick="toggleHashtag(\'{tag}\'); return false;" class="hashtag text-blue-500 hover:underline">{hashtag}</a>'
        return match.group(0)

    pattern = r'(https?://\S+)|(#\w+)'
    return re.sub(pattern, replace, text)

def extract_terms(text: str) -> set[str]:
    """
    Extracts valid terms from text, excluding stop words and short words.
    """
    # Basic stop words list
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
    
    # Remove URLs and hashtags first
    text = re.sub(r'(https?://\S+)|(#\w+)', '', text)
    
    # Find words (alphanumeric)
    words = re.findall(r'\b\w+\b', text.lower())
    
    valid_terms = set()
    for word in words:
        if len(word) > 2 and word not in STOP_WORDS:
            valid_terms.add(word)
            
    return valid_terms
