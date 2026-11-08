"""Conflux security: AEGIS gates, missing capability, untrusted actor."""

from __future__ import annotations

import os

import pytest

from conflux.security.authorization import (
    authorize_mutation,
    provision_operator,
    CONFLUX_CAPABILITIES,
)


@pytest.fixture
def aegis_on(monkeypatch):
    monkeypatch.setenv("CONFLUX_REQUIRE_AEGIS", "1")
    monkeypatch.delenv("AURORA_DASHBOARD_API_KEY", raising=False)
    try:
        from mods.aegis_42 import start_aegis, stop_aegis, get_aegis

        stop_aegis()
        start_aegis(node_id="test-node")
        yield get_aegis()
        stop_aegis()
    except Exception as e:
        pytest.skip(f"AEGIS unavailable: {e}")


def test_deny_without_actor(aegis_on):
    r = authorize_mutation(actor_id="", capability="conflux:project:create", api_key_ok=True)
    assert r.allowed is False
    assert r.reason == "actor_id_required"


def test_deny_unknown_actor(aegis_on):
    r = authorize_mutation(actor_id="ghost", capability="conflux:project:create", api_key_ok=True)
    assert r.allowed is False
    assert r.reason == "actor_unknown"


def test_deny_missing_capability(aegis_on):
    aegis_on.identity.register("bob", kind="worker", trust_level="untrusted")
    r = authorize_mutation(actor_id="bob", capability="conflux:project:create", api_key_ok=True)
    assert r.allowed is False
    assert r.reason == "capability_missing"


def test_allow_provisioned_operator(aegis_on):
    result = provision_operator("ops-1", granted_by="system")
    assert result["ok"] is True
    r = authorize_mutation(actor_id="ops-1", capability="conflux:project:create", api_key_ok=True)
    assert r.allowed is True
    assert r.reason == "authorized"


def test_deny_bad_api_key(monkeypatch, aegis_on):
    monkeypatch.setenv("AURORA_DASHBOARD_API_KEY", "secret")
    provision_operator("ops-2", granted_by="system")
    r = authorize_mutation(actor_id="ops-2", capability="conflux:build:create", api_key_ok=False)
    assert r.allowed is False
    assert r.reason == "api_key_invalid"


def test_fail_closed_when_aegis_required_but_stopped(monkeypatch):
    monkeypatch.setenv("CONFLUX_REQUIRE_AEGIS", "1")
    try:
        from mods.aegis_42 import stop_aegis

        stop_aegis()
    except Exception:
        pass
    # get_aegis may return None or disabled instance
    r = authorize_mutation(actor_id="anyone", capability="conflux:project:create", api_key_ok=True)
    # Either unavailable or actor_unknown / aegis_disabled_but_required
    assert r.allowed is False


def test_capability_catalog_complete():
    required = {
        "conflux:project:create",
        "conflux:source:add",
        "conflux:changeset:create",
        "conflux:changeset:reconcile",
        "conflux:changeset:approve",
        "conflux:build:create",
        "conflux:release:create",
        "conflux:release:promote",
        "conflux:deployment:plan",
        "conflux:deployment:execute",
        "conflux:deployment:rollback",
    }
    assert required.issubset(CONFLUX_CAPABILITIES)
