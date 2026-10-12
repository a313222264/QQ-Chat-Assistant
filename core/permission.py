"""权限判断：超级用户、群管理员、聊天白名单。"""


def is_superuser(cfg, user_id) -> bool:
    supers = cfg.get("admin.superusers", []) or []
    return str(user_id) in [str(s) for s in supers]


def is_group_admin(event: dict) -> bool:
    """群事件发送者是否为群主/群管理员（NapCat 在 sender.role 里直接给）。"""
    role = (event.get("sender") or {}).get("role", "")
    return role in ("admin", "owner")


def is_admin(cfg, event: dict) -> bool:
    """机器人管理员 = 超级用户 或 该群群主/管理员。"""
    if is_superuser(cfg, event.get("user_id")):
        return True
    if event.get("message_type") == "group":
        return is_group_admin(event)
    return False


def chat_allowed(cfg, event: dict) -> bool:
    """白名单过滤：空列表=不限；填了=只在这些会话里交互（存档不受限）。"""
    if event.get("message_type") == "group":
        wl = cfg.get("admin.whitelist_groups", []) or []
        return (not wl) or str(event.get("group_id")) in [str(x) for x in wl]
    wl = cfg.get("admin.whitelist_friends", []) or []
    return (not wl) or str(event.get("user_id")) in [str(x) for x in wl]
