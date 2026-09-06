import asyncio
import logging
import uuid
import httpx
from typing import Optional

from a2a.client.client import ClientConfig as A2AClientConfig
from a2a.client.client_factory import ClientFactory as A2AClientFactory
from a2a.types import AgentCard
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent, _compat
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.tools import ToolContext
from google.genai import types

from config.settings import settings
from app.auth import resolve_looker_token

logger = logging.getLogger(__name__)

async def _invoke_looker_a2a_agent(
    agent_name: str,
    agent_uuid: str,
    query: str,
    token: str,
    timeout_secs: float = 90.0,
) -> str:
    """Executes a natural language query against a native Looker A2A agent."""
    agent_url = f"{settings.looker_base_url.rstrip('/')}/api/4.0/a2a/agents/{agent_uuid}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    # Try native A2A JSON-RPC 2.0 sendMessage call
    payload = {
        "jsonrpc": "2.0",
        "method": "sendMessage",
        "id": 1,
        "params": {
            "message": {
                "role": "user",
                "parts": [{"text": query}],
            }
        },
    }
    
    try:
        async with httpx.AsyncClient(headers=headers, timeout=timeout_secs) as http_client:
            resp = await http_client.post(agent_url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("result", {})
                parts = result.get("parts", [])
                text_parts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
                text = "".join(text_parts).strip()
                if text:
                    return text
            elif resp.status_code in (401, 403):
                logger.error(f"Looker A2A authentication failed with status {resp.status_code}: {resp.text}")
                return f"Authentication error with Looker (HTTP {resp.status_code}). Please verify your Looker credentials."
            else:
                logger.warning(f"Looker A2A direct POST returned HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"Looker A2A direct JSON-RPC invocation failed: {e}. Falling back to RemoteA2aAgent.")

    # Fallback to RemoteA2aAgent
    card_dict = {
        "name": agent_name,
        "description": f"Looker agent {agent_name}",
        "version": "1.0.0",
        "url": agent_url,
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": "query_looker_data",
            "name": "Query Looker Data",
            "description": "Executes Looker analytical queries",
            "tags": ["looker", "data"],
        }],
    }
    card_obj = _compat.parse_agent_card(card_dict)
    agent_identifier = agent_name.strip().lower().replace(" ", "_").replace("-", "_")
    
    async with httpx.AsyncClient(headers=headers, timeout=timeout_secs) as http_client:
        client_config = A2AClientConfig(
            httpx_client=http_client,
            streaming=False,
            polling=False,
        )
        factory = A2AClientFactory(config=client_config)
        remote_agent = RemoteA2aAgent(
            name=agent_identifier,
            agent_card=card_obj,
            a2a_client_factory=factory,
        )
        
        session_service = InMemorySessionService()
        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        invocation_id = f"inv_{uuid.uuid4().hex[:8]}"
        
        session = await session_service.create_session(
            app_name="looker_orchestrator",
            user_id="end_user",
            session_id=session_id,
        )
        user_content = types.Content(role="user", parts=[types.Part(text=query)])
        await session_service.append_event(session, Event(invocation_id=invocation_id, author="user", content=user_content))
        
        ctx = InvocationContext(
            invocation_id=invocation_id,
            session_service=session_service,
            agent=remote_agent,
            session=session,
            user_content=user_content,
        )
        
        output_parts = []
        async for event in remote_agent.run_async(ctx):
            if event.error_message:
                logger.error(f"Error from remote agent {agent_name}: {event.error_message}")
                return f"Error querying Looker agent: {event.error_message}"
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        output_parts.append(part.text)
                        
        result = "".join(output_parts).strip()
        return result or "No content returned from Looker agent."

async def query_domain_agent_1(query: str, tool_context: ToolContext) -> str:
    """Queries the primary Looker domain agent for analytical metrics and business data.

    Args:
        query: The business question regarding primary domain data.
        tool_context: The ADK tool context containing session and OAuth state.
    """
    token = resolve_looker_token(tool_context)
    if not token:
        return "Authentication error: Looker user access token is not available in context. Please connect your Looker account."
    
    logger.info(f"Routing query to {settings.looker_agent_1_name} ({settings.looker_agent_1_uuid})...")
    return await _invoke_looker_a2a_agent(
        agent_name=settings.looker_agent_1_name,
        agent_uuid=settings.looker_agent_1_uuid,
        query=query,
        token=token,
    )

async def query_domain_agent_2(query: str, tool_context: ToolContext) -> str:
    """Queries the secondary Looker domain agent for analytical metrics and business data.

    Args:
        query: The business question regarding secondary domain data.
        tool_context: The ADK tool context containing session and OAuth state.
    """
    token = resolve_looker_token(tool_context)
    if not token:
        return "Authentication error: Looker user access token is not available in context. Please connect your Looker account."
    
    logger.info(f"Routing query to {settings.looker_agent_2_name} ({settings.looker_agent_2_uuid})...")
    return await _invoke_looker_a2a_agent(
        agent_name=settings.looker_agent_2_name,
        agent_uuid=settings.looker_agent_2_uuid,
        query=query,
        token=token,
    )

# Dynamically set tool docstrings based on configured domain agent definitions
query_domain_agent_1.__doc__ = f"""Queries {settings.looker_agent_1_name} for analytical metrics and business data. {settings.looker_agent_1_description}

Args:
    query: The business question regarding {settings.looker_agent_1_name} data.
    tool_context: The ADK tool context containing session and OAuth state.
"""

query_domain_agent_2.__doc__ = f"""Queries {settings.looker_agent_2_name} for analytical metrics and business data. {settings.looker_agent_2_description}

Args:
    query: The business question regarding {settings.looker_agent_2_name} data.
    tool_context: The ADK tool context containing session and OAuth state.
"""

# Backward compatibility aliases
query_ecommerce_sales_agent = query_domain_agent_1
query_ecomm_site_traffic_agent = query_domain_agent_2
