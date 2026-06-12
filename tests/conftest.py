import base64
from typing import Any, Callable


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class FakeApi:
    """A fake ``fetch`` transport.

    Routes are matched on the request URL by substring and return a
    ``(status, body)`` tuple. The most-specific (longest) matching key wins, so a
    route for ``/contents/README.md`` takes precedence over ``/contents``.
    Records every requested URL for assertions.
    """

    def __init__(self, routes: dict[str, tuple[int, Any]]):
        self.routes = routes
        self.calls: list[str] = []

    def fetch(self, method: str, url: str, *, token: str | None = None,
              timeout: int = 30) -> tuple[int, Any]:
        self.calls.append(url)
        best: tuple[int, tuple[int, Any]] | None = None
        for key, value in self.routes.items():
            if key in url and (best is None or len(key) > best[0]):
                best = (len(key), value)
        if best is not None:
            return best[1]
        return 404, {"message": f"no route for {url}"}


def make_fetch(routes: dict[str, tuple[int, Any]]) -> tuple[Callable[..., tuple[int, Any]], FakeApi]:
    api = FakeApi(routes)
    return api.fetch, api
