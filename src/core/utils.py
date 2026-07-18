import json
import re
import inflect
from queue import Queue

# Create an inflect engine
p = inflect.engine()

def get_singular_word(word: str) -> str:
    # If the word is plural, return singular; otherwise return as is
    singular = p.singular_noun(word)
    return singular if singular else word

def get_json_object(response_from_llm: str = ""):
    try:
        raw = response_from_llm

        # Try each ```json ... ``` code block first (handles multiple blocks correctly)
        for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw):
            try:
                data = json.loads(block.strip())
                if isinstance(data, dict):
                    return data
            except Exception:
                continue

        # Fall back: find each top-level {...} by tracking brace depth
        i = 0
        while i < len(raw):
            if raw[i] != '{':
                i += 1
                continue
            depth = 0
            for j in range(i, len(raw)):
                if raw[j] == '{':
                    depth += 1
                elif raw[j] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(raw[i:j+1])
                            if isinstance(data, dict):
                                return data
                        except Exception:
                            pass
                        i = j + 1
                        break
            else:
                break

        return None
    except Exception:
        return None

def remove_substring(s: str, token: str) -> str:
    # Split by comma, strip whitespace, filter out the exact token, then re-join with consistent formatting
    parts = [p.strip() for p in s.split(',')]
    filtered = [p for p in parts if p != token]
    return ', '.join(filtered)


