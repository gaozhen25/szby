import hashlib


def anonymize_user_id(user_id):
    if user_id in (None, ""):
        return ""
    return hashlib.sha256(str(user_id).strip().encode()).hexdigest()[:16]


def mask_nickname(nickname):
    value = str(nickname or "")
    if not value:
        return ""
    if len(value) <= 1:
        return "*"
    return f"{value[0]}***{value[-1]}" if len(value) > 2 else f"{value[0]}*"
