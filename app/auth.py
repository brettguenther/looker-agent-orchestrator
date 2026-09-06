import logging
import os
import yaml
from typing import Optional, Any
from google.adk.tools import ToolContext
from config.settings import settings

logger = logging.getLogger(__name__)

def _get_token_from_looker_cli() -> Optional[str]:
    """Reads active OAuth access token from local looker-cli config if available."""
    config_path = os.path.expanduser("~/.config/looker-cli/config.yaml")
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            if not isinstance(cfg, dict):
                return None
            active_profile = cfg.get("default", "argolis")
            profiles = cfg.get("profiles", {})
            profile = profiles.get(active_profile, {})
            token = profile.get("access_token")
            if token and isinstance(token, str):
                return token
    except Exception as e:
        logger.debug("Failed reading looker-cli config: %s", e)
    return None

def resolve_looker_token(tool_context: Optional[ToolContext] = None) -> Optional[str]:
    """
    Resolves the Looker Bearer token dynamically.
    1. Checks tool_context.state for 'temp:<AUTH_ID>' or '<AUTH_ID>' (injected by Gemini Enterprise).
    2. Checks environment settings (LOOKER_A2A_TOKEN).
    3. Falls back to local looker-cli config if in local developer mode.
    """
    auth_id = settings.looker_auth_id
    auth_id_short = auth_id.split("/")[-1] if auth_id else ""
    candidate_keys = [
        f"temp:{auth_id}",
        auth_id,
        f"temp:{auth_id_short}",
        auth_id_short,
        "temp:looker-orchestrator-auth",
        "looker-orchestrator-auth",
    ]

    # Check tool_context.state
    if tool_context and hasattr(tool_context, "state") and isinstance(tool_context.state, dict):
        logger.info(f"Inspecting tool_context.state keys: {list(tool_context.state.keys())}")
        for k in candidate_keys:
            if k and k in tool_context.state and tool_context.state[k]:
                logger.info(f"Looker token resolved from tool_context.state key: {k}")
                return str(tool_context.state[k])
        # Fuzzy search for any key starting with temp: or containing looker
        for k, v in tool_context.state.items():
            if (k.startswith("temp:") or "looker" in k.lower()) and v and isinstance(v, str):
                logger.info(f"Looker token dynamically resolved from tool_context.state matching key: {k}")
                return v

    # Check session state if present
    if tool_context and hasattr(tool_context, "session"):
        session = getattr(tool_context, "session", None)
        if session and hasattr(session, "state") and isinstance(session.state, dict):
            logger.info(f"Inspecting session.state keys: {list(session.state.keys())}")
            for k in candidate_keys:
                if k and k in session.state and session.state[k]:
                    logger.info(f"Looker token resolved from session.state key: {k}")
                    return str(session.state[k])
            for k, v in session.state.items():
                if (k.startswith("temp:") or "looker" in k.lower()) and v and isinstance(v, str):
                    logger.info(f"Looker token dynamically resolved from session.state matching key: {k}")
                    return v

    # Local environment override
    if settings.looker_a2a_token:
        logger.info("Using LOOKER_A2A_TOKEN from environment.")
        return settings.looker_a2a_token

    # Developer fallback
    cli_token = _get_token_from_looker_cli()
    if cli_token:
        logger.info("Using token from looker-cli config for local execution.")
        return cli_token

    logger.warning("No Looker access token could be resolved from context or environment.")
    return None
