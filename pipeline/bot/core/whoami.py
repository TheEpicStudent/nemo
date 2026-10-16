_cache = {}


def bot_user_id(client, name):
    if name not in _cache:
        _cache[name] = client.auth_test()["user_id"]
    return _cache[name]


def clear_cache():
    _cache.clear()
