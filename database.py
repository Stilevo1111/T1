def get_all_users():
    """Получение всех пользователей (для загрузки в кеш при старте)"""
    return _get_all_users_query(load_all=False, allow_non_steam=True)


def get_all_users_with_steam():
    return _get_all_users_query(load_all=False, allow_non_steam=False)

