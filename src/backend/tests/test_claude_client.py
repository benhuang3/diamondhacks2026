"""Unit tests for the Claude client wrapper and JSON extraction helpers."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_is_demo_mode_true_when_no_key(monkeypatch):
    from src.backend.agents import claude_client
    from src.config.settings import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)
    assert claude_client.is_demo_mode() is True


async def test_is_demo_mode_true_for_placeholder(monkeypatch):
    from src.backend.agents import claude_client
    from src.config.settings import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-xxxxx-placeholder", raising=False)
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)
    assert claude_client.is_demo_mode() is True


async def test_is_demo_mode_true_for_demo_string(monkeypatch):
    from src.backend.agents import claude_client
    from src.config.settings import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "DEMO", raising=False)
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)
    assert claude_client.is_demo_mode() is True


async def test_is_demo_mode_false_for_real_key(monkeypatch):
    from src.backend.agents import claude_client
    from src.config.settings import settings

    monkeypatch.setattr(
        settings, "anthropic_api_key", "sk-ant-abcdef-realkey-9999", raising=False
    )
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)
    assert claude_client.is_demo_mode() is False


async def test_is_demo_mode_respects_demo_mode_flag(monkeypatch):
    from src.backend.agents import claude_client
    from src.config.settings import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-real-9999", raising=False)
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    assert claude_client.is_demo_mode() is True


async def test_complete_raises_demo_fallback_in_demo_mode(monkeypatch):
    from src.backend.agents import claude_client
    from src.config.settings import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)

    client = claude_client.ClaudeClient()
    with pytest.raises(claude_client.DemoFallbackError):
        await client.complete("hello")


async def test_complete_wraps_sdk_errors_as_demo_fallback(monkeypatch):
    from src.backend.agents import claude_client
    from src.config.settings import settings

    monkeypatch.setattr(
        settings, "anthropic_api_key", "sk-ant-real-abcdefg-0000", raising=False
    )
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)

    client = claude_client.ClaudeClient()

    class Boom:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("boom")

    monkeypatch.setattr(client, "_client", Boom, raising=False)
    # _get_client short-circuits when _client is set.
    with pytest.raises(claude_client.DemoFallbackError):
        await client.complete("hi", system="sys")


async def test_complete_returns_text_from_content_blocks(monkeypatch):
    from src.backend.agents import claude_client
    from src.config.settings import settings

    monkeypatch.setattr(
        settings, "anthropic_api_key", "sk-ant-real-abcdefg-0000", raising=False
    )
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)

    class Block:
        def __init__(self, text):
            self.text = text

    class Msg:
        content = [Block("hello "), Block("world")]

    class Stub:
        class messages:
            @staticmethod
            def create(**kwargs):
                assert "model" in kwargs
                assert kwargs["messages"][0]["role"] == "user"
                return Msg()

    client = claude_client.ClaudeClient()
    monkeypatch.setattr(client, "_client", Stub, raising=False)
    out = await client.complete("prompt", system="sys", max_tokens=10)
    assert out == "hello \nworld"
