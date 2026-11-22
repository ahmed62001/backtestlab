"""Regression tests for provider catalog caching and shared cooldown.

Observed defect: the unauthenticated catalog did live upstream health probes on
every request (1.2-3.8s cold) and a challenged provider (Stooq) was retried by
every process. These tests pin the cache and the DB-backed cooldown contract.
"""

from __future__ import annotations

import pytest


def test_catalog_is_cached_in_dev_and_returns_copies(monkeypatch):
    from app.data_providers import registry

    calls: list[int] = []
    real_build = registry._build_provider_infos

    def counting_build():
        calls.append(1)
        return real_build()

    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setattr(registry, "_CATALOG_TTL_S", 60.0)
    monkeypatch.setattr(registry, "_build_provider_infos", counting_build)
    registry.clear_provider_info_cache()

    first = registry.provider_infos()
    second = registry.provider_infos()
    assert len(calls) == 1
    assert first == second
    # Callers must never be able to mutate the shared snapshot.
    first["items"].clear()
    assert registry.provider_infos()["items"]
    registry.clear_provider_info_cache()


def test_cooldown_parks_provider_and_catalog_reports_retry_after():
    from app.data_providers import registry
    from app.data_providers.cooldown import clear_cooldown, cooldown_status, set_cooldown

    clear_cooldown("stooq")
    assert cooldown_status("stooq")["active"] is False
    set_cooldown("stooq", 300, reason="UPSTREAM_BLOCKED")

    status = cooldown_status("stooq")
    assert status["active"] is True
    assert 1 <= status["retryAfter"] <= 300

    registry.clear_provider_info_cache()
    by_id = {item["id"]: item for item in registry.provider_infos()["items"]}
    stooq = by_id["stooq"]
    assert stooq["available"] is False
    assert stooq["retryAfter"] > 0
    assert "cooling down" in stooq["availableDetail"]
    clear_cooldown("stooq")


def test_fetch_bars_refuses_a_cooling_provider_without_calling_it(monkeypatch):
    from app.data_providers import registry
    from app.data_providers.base import ProviderError
    from app.data_providers.cooldown import clear_cooldown, set_cooldown
    from app.data_providers.stooq import StooqProvider

    called: list[int] = []

    def must_not_fetch(self, *args, **kwargs):
        called.append(1)
        raise AssertionError("cooling provider must not be called")

    monkeypatch.setattr(StooqProvider, "fetch_ohlcv_raw", must_not_fetch)
    clear_cooldown("stooq")
    set_cooldown("stooq", 300, reason="UPSTREAM_BLOCKED")
    try:
        with pytest.raises(ProviderError) as exc:
            registry.fetch_bars(
                "stooq", "AAPL", "2022-01-01", "2022-12-31", "1D", allow_fallback=False
            )
        assert exc.value.code == "PROVIDER_COOLDOWN"
        assert exc.value.retry_after and exc.value.retry_after > 0
        assert called == []
    finally:
        clear_cooldown("stooq")


def test_blocked_failure_records_cooldown(monkeypatch):
    from app.data_providers import registry
    from app.data_providers.base import ProviderError
    from app.data_providers.cooldown import clear_cooldown, cooldown_status
    from app.data_providers.stooq import StooqProvider

    def blocked(self, *args, **kwargs):
        raise ProviderError("stooq", "UPSTREAM_BLOCKED", "challenge")

    monkeypatch.setattr(StooqProvider, "fetch_ohlcv_raw", blocked)
    monkeypatch.setattr("app.data_providers.base.cache_read", lambda key: None)
    monkeypatch.setattr("app.data_providers.base.RETRY_ATTEMPTS", 1)
    clear_cooldown("stooq")
    with pytest.raises(ProviderError):
        registry.fetch_bars("stooq", "AAPL", "2022-01-01", "2022-12-31", "1D", allow_fallback=False)
    assert cooldown_status("stooq")["active"] is True
    clear_cooldown("stooq")
