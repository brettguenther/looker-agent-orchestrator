import logging
from google.adk.agents import Agent
from google.adk.apps import App
from config.settings import settings
from app.tools import query_domain_agent_1, query_domain_agent_2

logger = logging.getLogger(__name__)

ORCHESTRATOR_INSTRUCTION = f"""You are the Looker Multi-Agent Analytics Orchestrator.
Your role is to coordinate specialized native Looker Conversational Analytics agents to answer enterprise analytical questions across distinct business domains.

You have access to two specialized tools connected directly to Looker data models:
1. `query_domain_agent_1`: {settings.looker_agent_1_name} - {settings.looker_agent_1_description}
2. `query_domain_agent_2`: {settings.looker_agent_2_name} - {settings.looker_agent_2_description}

Rules:
- For domain-specific questions, delegate to the relevant specialized agent tool.
- For cross-domain inquiries spanning multiple areas, invoke both tools sequentially and synthesize a cohesive analysis.
- Always invoke the specialized tools to retrieve analytical data. Never assume an authentication or connection error persists from prior conversation turns without first attempting to query the tool.
- Present clean, executive-ready markdown answers highlighting key numerical metrics in bold.
- Do not fabricate metrics or dimensions not present in Looker explores. If the requested data is unmodeled, state so clearly.
"""

root_agent = Agent(
    name="looker_orchestrator",
    model=settings.model_name,
    instruction=ORCHESTRATOR_INSTRUCTION,
    tools=[
        query_domain_agent_1,
        query_domain_agent_2,
    ],
)

app = App(
    root_agent=root_agent,
    name="looker_orchestrator",
)
