"""Accessibility Scanner uAgent.

Wraps src.backend.workers.scan_worker.run_scan. Receives a ChatMessage
containing a storefront URL, runs the full scan pipeline, and returns
markdown-formatted findings.
"""

import os
import traceback
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

from ._workers import extract_url, run_accessibility_scan

load_dotenv()

scanner = Agent(
    name="accessibility_scanner",
    seed=os.environ["SCANNER_AGENT_SEED"],
    port=8001,
    mailbox=True,
)

chat = Protocol(spec=chat_protocol_spec)


@chat.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    text = "".join(c.text for c in msg.content if isinstance(c, TextContent))
    ctx.logger.info(f"received from {sender}: {text!r}")

    # Acknowledge receipt.
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.utcnow(),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    url = extract_url(text)
    if not url:
        reply_text = (
            "Please include a storefront URL (e.g. https://example.com). "
            "The scanner only accepts http(s) links."
        )
    else:
        ctx.logger.info(f"starting accessibility scan for {url}")
        try:
            reply_text = await run_accessibility_scan(url)
        except Exception as e:  # noqa: BLE001
            ctx.logger.error(f"scan failed for {url}: {e}")
            ctx.logger.debug(traceback.format_exc())
            reply_text = f"Scan failed for {url}: {e}"
    await ctx.send(
        sender,
        ChatMessage(
            timestamp=datetime.utcnow(),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=reply_text),
                EndSessionContent(type="end-session"),
            ],
        ),
    )


@chat.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")


scanner.include(chat, publish_manifest=True)


if __name__ == "__main__":
    scanner.run()
