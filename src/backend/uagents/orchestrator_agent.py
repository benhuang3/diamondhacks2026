"""Storefront Orchestrator uAgent.

Public entry point for ASI:One. Fans out incoming user requests to the
scanner and competitor sub-agents, then merges their replies into a
single response.

Requires SCANNER_AGENT_ADDRESS and COMPETITOR_AGENT_ADDRESS in .env.

Concurrency note: session state is a single slot. Two users querying
simultaneously will clobber each other (last-write-wins on pending_user).
Acceptable for hackathon demo; proper fix requires correlation tokens
echoed by sub-agents in their replies.
"""

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

SCANNER_ADDRESS = os.environ.get("SCANNER_AGENT_ADDRESS", "")
COMPETITOR_ADDRESS = os.environ.get("COMPETITOR_AGENT_ADDRESS", "")

orchestrator = Agent(
    name="storefront_reviewer",
    seed=os.environ["ORCHESTRATOR_AGENT_SEED"],
    port=8003,
    mailbox=True,
)

chat = Protocol(spec=chat_protocol_spec)


def _text_of(msg: ChatMessage) -> str:
    return "".join(c.text for c in msg.content if isinstance(c, TextContent))


@chat.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
    text = _text_of(msg)
    ctx.logger.info(f"received from {sender}: {text!r}")

    # Ack the user.
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.utcnow(),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    sub_agents = {SCANNER_ADDRESS, COMPETITOR_ADDRESS} - {""}
    is_sub_agent_reply = sender in sub_agents

    if not is_sub_agent_reply:
        # New user request — reset session state.
        if not SCANNER_ADDRESS or not COMPETITOR_ADDRESS:
            await ctx.send(
                sender,
                ChatMessage(
                    timestamp=datetime.utcnow(),
                    msg_id=uuid4(),
                    content=[
                        TextContent(
                            type="text",
                            text=(
                                "Orchestrator is not fully configured: sub-agent "
                                "addresses missing. Set SCANNER_AGENT_ADDRESS and "
                                "COMPETITOR_AGENT_ADDRESS in .env."
                            ),
                        ),
                        EndSessionContent(type="end-session"),
                    ],
                ),
            )
            return

        ctx.storage.set("pending_user", sender)
        ctx.storage.set("scanner_done", False)
        ctx.storage.set("competitor_done", False)
        ctx.storage.set("scanner_text", "")
        ctx.storage.set("competitor_text", "")
        ctx.logger.info(f"fanning out request to scanner + competitor (user={sender})")
        for addr in (SCANNER_ADDRESS, COMPETITOR_ADDRESS):
            await ctx.send(
                addr,
                ChatMessage(
                    timestamp=datetime.utcnow(),
                    msg_id=uuid4(),
                    content=[TextContent(type="text", text=text)],
                ),
            )
        return

    # Sub-agent reply — drop it if there's no active session (late/dup).
    pending_user = ctx.storage.get("pending_user")
    if not pending_user:
        ctx.logger.warning(
            f"Ignoring late reply from {sender} — no active session."
        )
        return

    if sender == SCANNER_ADDRESS:
        ctx.storage.set("scanner_done", True)
        ctx.storage.set("scanner_text", text)
    elif sender == COMPETITOR_ADDRESS:
        ctx.storage.set("competitor_done", True)
        ctx.storage.set("competitor_text", text)

    if not (ctx.storage.get("scanner_done") and ctx.storage.get("competitor_done")):
        return

    # Both sub-agents replied — snapshot + clear state BEFORE sending so any
    # duplicate sub-agent replies don't re-trigger this merge.
    scanner_text = ctx.storage.get("scanner_text") or ""
    competitor_text = ctx.storage.get("competitor_text") or ""
    ctx.storage.set("pending_user", None)
    ctx.storage.set("scanner_done", False)
    ctx.storage.set("competitor_done", False)
    ctx.storage.set("scanner_text", "")
    ctx.storage.set("competitor_text", "")

    merged = (
        "## Accessibility Scan\n"
        f"{scanner_text}\n\n"
        "## Competitor Analysis\n"
        f"{competitor_text}"
    )
    await ctx.send(
        pending_user,
        ChatMessage(
            timestamp=datetime.utcnow(),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=merged),
                EndSessionContent(type="end-session"),
            ],
        ),
    )


@chat.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    ctx.logger.debug(f"ack from {sender} for {msg.acknowledged_msg_id}")


orchestrator.include(chat, publish_manifest=True)


if __name__ == "__main__":
    orchestrator.run()
