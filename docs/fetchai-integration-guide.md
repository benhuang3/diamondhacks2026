# Fetch.ai Integration Guide — DiamondHacks 2026

Step-by-step guide for integrating this project with Fetch.ai's Agentverse and ASI:One for the DiamondHacks 2026 Fetch.ai track.

## Track Requirements (Quick Reference)

- Build agents, register on **Agentverse**, expose via **ChatProtocol** so **ASI:One** can discover and call them
- No custom frontend needed — demo happens inside ASI:One chat
- Underlying LLM can be anything (Claude, OpenAI, etc.) — LLM choice doesn't affect the track
- **Deliverables**: public GitHub repo, 2 Innovation Lab badges in README, 3-5 min demo video, ASI:One chat session URL, Agentverse agent profile URLs
- **Optional but scored**: Payment Protocol (FET or Skyfire)
- **Promo code**: `DIAMONDHACKS` or `DIAMONDHACKSAV` for 1 month free ASI:One Pro + Agentverse Premium

## Agent Architecture for This Project

| Agent | Wraps | Registered on Agentverse? | Public in ASI:One? |
|---|---|---|---|
| **StorefrontOrchestratorAgent** | Coordinates the other two | Yes | **Yes — promote this one** |
| **AccessibilityScannerAgent** | `scan_worker.py` | Yes | Internal |
| **CompetitorDiscoveryAgent** | `competitor_worker.py` | Yes | Internal |

All three must be registered (they need addresses to message each other), but only the Orchestrator needs a discovery-optimized profile.

---

## Step 1: Install the SDK

```bash
cd /Users/benjaminhuang/gitssh/diamondhacks2026
source .venv/bin/activate   # or however you activate your venv
pip install uagents
```

Verify:
```bash
python -c "import uagents; print(uagents.__version__)"
```

## Step 2: Generate 3 Unique Seeds

Each agent needs a stable seed phrase — it deterministically derives the `agent1q...` address, so the **same seed = same address** across restarts. If you lose the seed, you lose the agent identity.

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Run 3 times. Add to `.env`:

```bash
SCANNER_AGENT_SEED=<hex1>
COMPETITOR_AGENT_SEED=<hex2>
ORCHESTRATOR_AGENT_SEED=<hex3>
```

## Step 3: Create a Minimal "Hello World" Agent First

Before wiring up your workers, prove the mailbox flow works with one simple agent. Create `src/backend/uagents/scanner_agent.py`:

```python
import os
from datetime import datetime
from uuid import uuid4
from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatMessage, ChatAcknowledgement, chat_protocol_spec,
    TextContent, EndSessionContent,
)

load_dotenv()

scanner = Agent(
    name="accessibility_scanner",
    seed=os.environ["SCANNER_AGENT_SEED"],
    port=8001,
    mailbox=True,
)

chat = Protocol(spec=chat_protocol_spec)

@chat.on_message(ChatMessage)
async def handle(ctx: Context, sender: str, msg: ChatMessage):
    text = "".join(c.text for c in msg.content if isinstance(c, TextContent))
    ctx.logger.info(f"received from {sender}: {text}")
    # ack first
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.utcnow(), acknowledged_msg_id=msg.msg_id))
    # reply
    await ctx.send(sender, ChatMessage(
        timestamp=datetime.utcnow(), msg_id=uuid4(),
        content=[
            TextContent(type="text", text=f"scanner stub received: {text}"),
            EndSessionContent(type="end-session"),
        ],
    ))

@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass

scanner.include(chat, publish_manifest=True)

if __name__ == "__main__":
    scanner.run()
```

## Step 4: Run It

```bash
python -m src.backend.uagents.scanner_agent
```

On **first startup**, you'll see output like:

```
INFO:     [accessibility_scanner]: Starting agent with address: agent1qvx...
INFO:     [accessibility_scanner]: Agent inspector available at https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A8001&address=agent1qvx...
INFO:     [accessibility_scanner]: Starting mailbox client for https://agentverse.ai
INFO:     [accessibility_scanner]: Mailbox access token acquired
INFO:     [accessibility_scanner]: Manifest published successfully: AgentChatProtocol
```

**Copy the Inspector URL** and open it in your browser.

## Step 5: Connect It to Your Agentverse Account

In the Inspector page:

1. Click **"Connect"** (top right)
2. Sign in to Agentverse with your account
3. Choose **"Mailbox"** as connection method
4. Confirm — the agent is now reachable via Agentverse's mailbox server at its `agent1q...` address

Go to https://agentverse.ai → **My Agents** → you should see `accessibility_scanner` listed. Click it, fill in the Name / README / Tags.

### What to Put in Each Agent's Agentverse Profile

**StorefrontOrchestratorAgent** (the public one — make this discoverable):
- **Name**: `Storefront Reviewer`
- **Short description**: "Analyzes e-commerce storefronts for accessibility issues and benchmarks them against competitors."
- **README** (verbose + keyword-rich — ASI:One matches against this):
  ```
  Input: a storefront URL (Shopify, WooCommerce, or any e-commerce site).

  What it does:
  1. Runs an accessibility scan (WCAG findings, alt text, contrast, interactive elements)
  2. Discovers 5-8 competitor storefronts in the same niche
  3. Synthesizes a strategy brief with pricing comparison and recommendations

  Example prompts:
  - "Review https://mystore.com for accessibility and competitors"
  - "Analyze this Shopify storefront: https://..."
  - "Benchmark https://... against similar stores"

  Output: findings with severity, competitor snapshots, and a ranked recommendation list.
  ```
- **Tags**: `innovationlab`, `hackathon`, `ecommerce`, `accessibility`, `competitive-analysis`, `shopify`, `wcag`

**AccessibilityScannerAgent** (internal):
- **Name**: `Accessibility Scanner (internal)`
- **Short description**: "Internal scanner agent. Called by Storefront Reviewer."
- **Tags**: `innovationlab`, `internal`

**CompetitorDiscoveryAgent** (internal):
- **Name**: `Competitor Discovery (internal)`
- **Short description**: "Internal competitor discovery agent. Called by Storefront Reviewer."
- **Tags**: `innovationlab`, `internal`

## Step 6: Repeat for the Other Two Agents

Create `competitor_agent.py` (port `8002`) and `orchestrator_agent.py` (port `8003`) with the same skeleton but different seeds/names. Run each in its own terminal:

```bash
# Terminal 1
python -m src.backend.uagents.scanner_agent
# Terminal 2
python -m src.backend.uagents.competitor_agent
# Terminal 3
python -m src.backend.uagents.orchestrator_agent
```

Connect each one's Inspector URL to Agentverse once.

### Hardcode Sub-Agent Addresses in the Orchestrator

After all 3 are registered and have `agent1q...` addresses, add the scanner + competitor addresses to `.env`:

```bash
SCANNER_AGENT_ADDRESS=agent1q...
COMPETITOR_AGENT_ADDRESS=agent1q...
```

The orchestrator uses these to `ctx.send(SCANNER_AGENT_ADDRESS, ...)` — no discovery needed between your own agents.

## Step 7: (Optional) Run All 3 from One Process with Bureau

Once you've verified each works individually, consolidate into `src/backend/uagents/run_all.py`:

```python
from uagents import Bureau
from src.backend.uagents.scanner_agent import scanner
from src.backend.uagents.competitor_agent import competitor
from src.backend.uagents.orchestrator_agent import orchestrator

bureau = Bureau()
bureau.add(scanner)
bureau.add(competitor)
bureau.add(orchestrator)

if __name__ == "__main__":
    bureau.run()
```

```bash
python -m src.backend.uagents.run_all
```

## Step 8: Verify in ASI:One

Open https://asi1.ai/ → send a message like `"@accessibility_scanner hello"` or a natural prompt matching your orchestrator's description. You should see the request hit your terminal logs and a reply come back.

**Save the chat session URL** for your hackathon submission.

---

## Troubleshooting

- **"Address already in use" on port 8001** — pick different ports or kill the old process: `lsof -ti:8001 | xargs kill`
- **Inspector URL not appearing** — make sure `mailbox=True` is set and you have internet (it connects outbound to `agentverse.ai`)
- **Agent disconnects from mailbox** — leave the process running; kill it and restart to reconnect
- **Can't find agent in ASI:One** — check Agentverse → agent profile → **Protocols** tab shows `AgentChatProtocol`, and the profile has a descriptive README

---

## Submission README Template

```markdown
## Agents on Agentverse
- **[Entry Point] Storefront Reviewer** — `agent1q...` [profile](https://agentverse.ai/agents/details/agent1q.../profile)
- Accessibility Scanner (internal) — `agent1q...` [profile](...)
- Competitor Discovery (internal) — `agent1q...` [profile](...)

Talk to the Storefront Reviewer in ASI:One: [chat session](https://asi1.ai/chat/...)

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-DiamondHacks2026-blue)
```

---

## Project Structure

```
src/backend/
  workers/              # keep as-is
    scan_worker.py
    competitor_worker.py
  uagents/              # new directory
    __init__.py
    scanner_agent.py       # wraps scan_worker
    competitor_agent.py    # wraps competitor_worker
    orchestrator_agent.py  # calls the other two
    run_all.py             # spawns all three via Bureau
```

---

## Key Docs

- https://docs.agentverse.ai — registration, mailbox
- https://innovationlab.fetch.ai/resources/docs/intro — ChatProtocol examples
- https://docs.asi1.ai/ — ASI:One integration
- https://www.fetch.ai/events/hackathons/diamond-hacks-2026/hackpack — track requirements
