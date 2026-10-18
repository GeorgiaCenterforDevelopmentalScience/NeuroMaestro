import pytest
from flask import Flask

from neuromaestro.interface.auth import install_token_auth

_TOKEN = "s3cret-token"
_COOKIE = "neuromaestro_token_8050"


@pytest.fixture
def client():
    server = Flask(__name__)

    @server.route("/")
    def index():
        return "ok"

    @server.route("/_dash-update-component", methods=["POST"])
    def update():
        return "updated"

    install_token_auth(server, _TOKEN, _COOKIE)
    return server.test_client()


def test_request_without_token_is_rejected(client):
    assert client.get("/").status_code == 403
    assert client.post("/_dash-update-component").status_code == 403


@pytest.mark.parametrize("bad", ["wrong", "", "s3cret-toke", "ünïcode"])
def test_wrong_token_is_rejected_and_sets_no_cookie(client, bad):
    resp = client.get("/", query_string={"token": bad})
    assert resp.status_code == 403
    assert client.get_cookie(_COOKIE) is None


def test_right_token_sets_cookie_and_strips_it_from_url(client):
    resp = client.get("/", query_string={"token": _TOKEN})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    cookie = client.get_cookie(_COOKIE)
    assert cookie.value == _TOKEN
    assert cookie.http_only
    assert cookie.same_site == "Strict"


def test_cookie_admits_later_requests(client):
    client.get("/", query_string={"token": _TOKEN})
    assert client.get("/").data == b"ok"
    assert client.post("/_dash-update-component").data == b"updated"


def test_forged_cookie_is_rejected(client):
    client.set_cookie(_COOKIE, "forged")
    assert client.get("/").status_code == 403


def test_rejection_survives_a_catch_all_error_handler():
    # Dash dev tools turn any raised error into a 500 traceback page.
    server = Flask(__name__)
    server.route("/")(lambda: "ok")
    server.errorhandler(Exception)(lambda e: ("traceback", 500))
    install_token_auth(server, _TOKEN, _COOKIE)
    assert server.test_client().get("/").status_code == 403


def test_launcher_binds_loopback_with_token_and_no_debugger(monkeypatch, tmp_path):
    import neuromaestro.interface.auth as auth_mod
    from neuromaestro.interface import run_gui
    from neuromaestro.interface.app import app

    monkeypatch.delenv("_NEUROMAESTRO_GUI_TOKEN", raising=False)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["neuromaestro-gui", "--debug", "--config-dir", str(tmp_path)])
    installed = {}
    monkeypatch.setattr(auth_mod, "install_token_auth",
                        lambda server, token, cookie: installed.update(token=token, cookie=cookie))
    runs = []
    monkeypatch.setattr(app, "run", lambda **kw: runs.append(kw))

    run_gui.main()

    assert installed["token"] and installed["cookie"] == "neuromaestro_token_8050"
    assert runs == [{"debug": True, "host": "127.0.0.1", "port": 8050,
                     "use_reloader": True, "use_debugger": False}]
