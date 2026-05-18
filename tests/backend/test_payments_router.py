"""支付路由注册顺序：避免 /pending、/status 被 /{payment_id} 吞掉。"""

from backend.api.routers import payments as payments_module


def test_get_static_paths_registered_before_payment_id():
    router = payments_module.router
    get_paths: list[str] = []
    for route in router.routes:
        methods = getattr(route, "methods", None) or set()
        if "GET" in methods:
            get_paths.append(route.path)

    # FastAPI 会把 prefix 拼进 route.path（如 /payments/pending）
    idx = {p: i for i, p in enumerate(get_paths)}
    assert idx["/payments/pending"] < idx["/payments/{payment_id}"]
    assert idx["/payments/status/{status}"] < idx["/payments/{payment_id}"]
    assert idx["/payments/user/{telegram_id}"] < idx["/payments/{payment_id}"]
