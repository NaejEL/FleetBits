"""Smoke test for the Fleet UI application factory.

WHAT THIS COVERS
    That `server.py` imports, that the Flask application object is built, and
    that every blueprint it registers is reachable. In practice this is what
    fails when a dependency bump breaks the component: Flask, Jinja2 or
    requests changing an API that the import path touches.

WHAT THIS DOES NOT COVER
    Anything a request would exercise. No route is called, no template is
    rendered, no response is asserted, no interaction with the Fleet API is
    checked. A route that returns the wrong data, a template that raises at
    render time, a permission check that is missing — none of that is caught
    here. This suite is not a substitute for test coverage of ui/; it is the
    minimum needed for "the dependency bump did not break the component" to
    mean something rather than nothing.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest
from flask import Flask

# ui/server.py refuses to build the application unless SECRET_KEY is set, is not
# the insecure default and is at least 32 characters long. The two values below
# are throw-away inputs for that guard, never credentials: nothing signs
# anything here, and no server is started.
IMPORT_TIME_SIGNING_VALUE = "ui-smoke-test-value-not-a-credential-0123456789012345"
REJECTED_SIGNING_VALUE = "too-short"

# Every blueprint server.py registers. Listed here rather than derived from the
# module, so dropping a registration fails this test instead of shrinking it.
EXPECTED_BLUEPRINTS = frozenset(
    {
        "auth",
        "inventory",
        "deployments",
        "hotfixes",
        "audit",
        "admin",
        "packages",
        "monitoring",
    }
)


@pytest.fixture()
def ui_server(monkeypatch: pytest.MonkeyPatch):
    """Import ui/server.py from a clean module state, with a usable secret key."""
    monkeypatch.setenv("SECRET_KEY", IMPORT_TIME_SIGNING_VALUE)
    monkeypatch.setenv("FLASK_DEBUG", "false")
    # load_dotenv() in server.py must not pick up a developer's local .env and
    # change what this test measures.
    monkeypatch.setenv("FLEET_API_URL", "http://fleet-api.invalid:8000")
    for name in [m for m in sys.modules if m == "server" or m.startswith("blueprints")]:
        del sys.modules[name]
    return importlib.import_module("server")


def test_the_application_is_built(ui_server) -> None:
    """The module-level Flask application exists and is a Flask application."""
    assert isinstance(ui_server.app, Flask)


def test_every_blueprint_is_registered(ui_server) -> None:
    """Each blueprint imported by server.py is attached to the application."""
    assert set(ui_server.app.blueprints) == set(EXPECTED_BLUEPRINTS)


def test_the_url_map_is_populated(ui_server) -> None:
    """The blueprints contributed routes: an empty map means nothing was wired."""
    routes = {rule.rule for rule in ui_server.app.url_map.iter_rules()}
    assert "/" in routes
    # Flask always registers /static/<path:filename>; the map must hold more.
    assert len(routes) > 2, f"only {len(routes)} route(s) registered: {sorted(routes)}"


def test_the_session_cookie_hardening_survives_the_build(ui_server) -> None:
    """The cookie flags server.py sets are the ones the application ends up with."""
    config = ui_server.app.config
    assert config["SESSION_COOKIE_HTTPONLY"] is True
    assert config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert config["SESSION_COOKIE_SECURE"] is True


def test_the_application_refuses_an_insecure_secret_key(monkeypatch) -> None:
    """The guard in server.py is part of what "the application builds" means."""
    monkeypatch.setenv("SECRET_KEY", REJECTED_SIGNING_VALUE)
    for name in [m for m in sys.modules if m == "server" or m.startswith("blueprints")]:
        del sys.modules[name]
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        importlib.import_module("server")
    # Leave no half-imported module behind for the next test.
    sys.modules.pop("server", None)

