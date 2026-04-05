"""Test client that sends a ChatMessage to the orchestrator and prints the reply."""

import os
from datetime import datetime
from uuid import uuid4

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

load_dotenv()

ORCHESTRATOR_ADDRESS = os.environ.get(
    "ORCHESTRATOR_AGENT_ADDRESS",
    # derived from ORCHESTRATOR_AGENT_SEED — overridden if env var set
    "",
)

client = Agent(
    name="test_client",
    seed="test-client-seed-please-change-me",
    port=8004,
    mailbox=True,
)

chat = Protocol(spec=chat_protocol_spec)


@client.on_event("startup")
async def on_start(ctx: Context) -> None:
    ctx.logger.info(f"test client address: {client.address}")
    target = ORCHESTRATOR_ADDRESS or ctx.storage.get("orchestrator_address") or ""
    if not target:
        ctx.logger.error("ORCHESTRATOR_AGENT_ADDRESS not set; cannot send test message")
        return
    ctx.logger.info(f"sending test message to orchestrator: {target}")
    await ctx.send(
        target,
        ChatMessage(
            timestamp=datetime.utcnow(),
            msg_id=uuid4(),
            content=[TextContent(type="text", text="https://example-store.com")],
        ),
    )


@chat.on_message(ChatMessage)
async def on_reply(ctx: Context, sender: str, msg: ChatMessage) -> None:
    text = "".join(c.text for c in msg.content if isinstance(c, TextContent))
    ctx.logger.info(f"REPLY from {sender}:\n{text}\n")
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.utcnow(), acknowledged_msg_id=msg.msg_id
        ),
    )


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    ctx.logger.debug(f"ack from {sender}")


client.include(chat, publish_manifest=True)


if __name__ == "__main__":
    client.run()
