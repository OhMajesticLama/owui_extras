from typing import List, Dict, Optional, Tuple


def get_last_message(
    messages: List[Dict[str, str]], role: str
) -> Tuple[Optional[Dict[str, str]], Optional[int]]:
    """
    Get last message from `role` and its index.
    messages:
        Dictionary of messages, passed as body['messages'] to the inlet method.
    """
    for i, m in enumerate(reversed(messages)):
        if m.get("role") == role:
            return (m, len(messages) - i - 1)
    return (None, None)
