import hmac

from flask import abort, redirect, request


def install_token_auth(server, token, cookie_name):
    """Reject every request that carries neither the launch token nor its cookie."""
    expected = token.encode()

    @server.before_request
    def _check_token():
        supplied = request.args.get("token")
        if supplied is not None:
            if not hmac.compare_digest(supplied.encode(), expected):
                abort(403)
            # Drop the token from the address bar once the cookie is set.
            response = redirect(request.path)
            response.set_cookie(cookie_name, token, httponly=True, samesite="Strict")
            return response
        if not hmac.compare_digest(request.cookies.get(cookie_name, "").encode(), expected):
            abort(403)
