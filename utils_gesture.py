import re


def parse_gestures(text: str):
    """
    Finds all [gesture] tags in text.
    Returns (clean_text, list_of_gestures)
    Each gesture in list: {"type": "...", "index": character_index_in_clean_text}
    """
    gestures = []
    clean_text = ""
    last_end = 0
    
    # Regex to find [smile], [nod], etc.
    # We only match alphanumeric and underscores inside brackets to avoid catching e.g. [1] references
    pattern = re.compile(r'\[([a-zA-Z0-9_]+)\]')
    
    for match in pattern.finditer(text):
        start, end = match.span()
        gesture_type = match.group(1)
        
        # Add the text before the tag
        clean_text += text[last_end:start]
        
        # Record the gesture at the current length of clean_text
        gestures.append({
            "type": gesture_type,
            "index": len(clean_text)
        })
        
        last_end = end
        
    clean_text += text[last_end:]
    return clean_text.strip(), gestures
