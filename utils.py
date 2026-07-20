def _telegram_error_contains(error: Exception, *phrases: str) -> bool:
    """Проверяет, содержит ли текст ошибки любую из переданных фраз (регистронезависимо)."""
    if error is None:
        return False
    msg = str(error).lower()
    return any(p.lower() in msg for p in phrases)