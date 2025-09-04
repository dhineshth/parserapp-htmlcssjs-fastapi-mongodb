# from typing import Optional

# def to_init_caps(name: Optional[str]) -> Optional[str]:
#     if not name:
#         return name
#     return ' '.join(word.capitalize() for word in name.split())

from typing import Optional

def to_init_caps(name: Optional[str]) -> Optional[str]:
    if not name:
        return name

    def format_word(word):
        # If the word is full uppercase, keep as is
        if word.isupper():
            return word
        # Otherwise, capitalize only the first letter
        return word[:1].upper() + word[1:].lower()

    return ' '.join(format_word(word) for word in name.split())
