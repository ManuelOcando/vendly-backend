"""
Guards on how routers are mounted, not on what the endpoints do.

The bug that motivated this: api/v1/cart.py declares its paths as "/create" and
"/{cart_id}", and router.py included it without a prefix. So GET
/api/v1/{cart_id} existed as a catch-all, and because FastAPI matches in
registration order it swallowed every single-segment GET declared after it -
/api/v1/customers, /api/v1/post-sale-requests and /api/v1/appointments each
resolved to get_cart and answered 404 "Cart not found or expired". Three
endpoints the frontend calls, unreachable, and every test passed because tests
call the handlers rather than resolving URLs.
"""
import pytest
from fastapi.routing import APIRoute

from main import app

API_PREFIX = "/api/v1"


def api_routes():
    return [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith(API_PREFIX)]


def tail(path):
    return path[len(API_PREFIX):].strip("/")


class TestNoWildcardShadowsLiteralRoutes:
    def test_no_route_is_a_bare_path_parameter_under_the_api_prefix(self):
        # /api/v1/{anything} matches every single-segment path, so it can only
        # ever be a trap. A router whose paths start at "/{...}" is missing its
        # prefix.
        offenders = [
            f"{sorted(r.methods)} {r.path}"
            for r in api_routes()
            if "/" not in tail(r.path) and tail(r.path).startswith("{")
        ]
        assert not offenders, (
            "these routes swallow every single-segment request under "
            f"{API_PREFIX}: {offenders}"
        )

    def test_literal_routes_are_not_shadowed_by_an_earlier_wildcard(self):
        """No literal segment may sit behind a wildcard at the same depth.

        Generalises the specific bug: FastAPI takes the first match, so a
        wildcard registered earlier wins over a literal registered later at the
        same depth, whatever the depth is.
        """
        seen_wildcards = []  # (depth, method, path) already registered
        shadowed = []

        for route in api_routes():
            segments = tail(route.path).split("/")
            for method in route.methods:
                for depth, method_, path_ in seen_wildcards:
                    if method_ != method or depth >= len(segments):
                        continue
                    other = tail(path_).split("/")
                    if len(other) != len(segments):
                        continue
                    # same shape, and every segment either matches or is the
                    # wildcard that would absorb it
                    if all(
                        a == b or a.startswith("{")
                        for a, b in zip(other, segments)
                    ) and not segments[depth].startswith("{"):
                        shadowed.append(f"{method} {route.path} hidden by {path_}")

            for index, segment in enumerate(segments):
                if segment.startswith("{"):
                    for method in route.methods:
                        seen_wildcards.append((index, method, route.path))

        assert not shadowed, "unreachable routes: " + "; ".join(sorted(set(shadowed)))


class TestRoutesTheFrontendCalls:
    """Paths hardcoded in vendly-frontend. If one moves, that client breaks."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/v1/customers"),
        ("POST", "/api/v1/cart/create"),
        ("GET", "/api/v1/cart/{cart_id}"),
        ("PUT", "/api/v1/cart/{cart_id}/items"),
        ("PUT", "/api/v1/cart/{cart_id}/customer"),
        ("GET", "/api/v1/health"),
    ])
    def test_route_exists(self, method, path):
        assert any(
            r.path == path and method in r.methods for r in api_routes()
        ), f"{method} {path} is not registered"

    def test_cart_routes_live_under_the_cart_prefix(self):
        cart_paths = {
            r.path for r in api_routes()
            if r.endpoint.__module__ == "api.v1.cart"
        }
        assert cart_paths, "no cart routes found"
        for path in cart_paths:
            assert path.startswith("/api/v1/cart/"), (
                f"{path} escaped the /cart prefix"
            )
