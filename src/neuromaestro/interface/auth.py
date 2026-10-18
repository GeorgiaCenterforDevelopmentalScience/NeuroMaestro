import hmac

from flask import redirect, request


_FORBIDDEN = ("Forbidden: open the link printed when the GUI started.", 403)


def install_token_auth(server, token, cookie_name):
    """Reject every request that carries neither the launch token nor its cookie."""
    expected = token.encode()

    @server.before_request
    def _check_token():
        supplied = request.args.get("token")
        if supplied is not None:
            # Returned, not raised: Dash dev tools render raised errors as tracebacks.
            if not hmac.compare_digest(supplied.encode(), expected):
                return _FORBIDDEN
            # Drop the token from the address bar once the cookie is set.
            response = redirect(request.path)
            response.set_cookie(cookie_name, token, httponly=True, samesite="Strict")
            return response
        if not hmac.compare_digest(request.cookies.get(cookie_name, "").encode(), expected):
            return _FORBIDDEN
