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
