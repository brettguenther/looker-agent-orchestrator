# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Authentication and token resolution for Looker and Gemini Enterprise."""

import logging
import os
from typing import Optional

import httpx
import yaml
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


def _get_token_from_client_credentials() -> Optional[str]:
    """Authenticates to Looker using client credentials if configured in environment."""
    client_id = os.environ.get("LOOKER_CLIENT_ID")
    client_secret = os.environ.get("LOOKER_CLIENT_SECRET")
    base_url = settings.looker_base_url

    if client_id and client_secret and base_url:
        try:
            resp = httpx.post(
                f"{base_url.rstrip('/')}/api/4.0/login",
                data={"client_id": client_id, "client_secret": client_secret},
                timeout=10.0,
            )
            if resp.status_code == 200:
                token = resp.json().get("access_token")
                if token:
                    logger.info("Successfully fetched fresh Looker access token via client credentials.")
                    return token
        except Exception as e:
            logger.debug("Failed Looker client credentials authentication: %s", e)
    return None


def resolve_looker_token(tool_context: Optional[ToolContext] = None) -> Optional[str]:
    """Resolves the Looker Bearer token dynamically.

    1. Checks tool_context.state for 'temp:<AUTH_ID>' or '<AUTH_ID>' (injected by Gemini Enterprise).
    2. Checks session.state for injected tokens.
    3. Checks environment settings (LOOKER_A2A_TOKEN).
    4. Falls back to local looker-cli config or client credentials for local developer testing.
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

    # 1. Check tool_context.state (primary path in Gemini Enterprise)
    if tool_context and hasattr(tool_context, "state") and isinstance(tool_context.state, dict):
        for k in candidate_keys:
            if k and k in tool_context.state and tool_context.state[k]:
                logger.info(f"Looker token resolved from tool_context.state key: {k}")
                return str(tool_context.state[k])
        for k, v in tool_context.state.items():
            if (k.startswith("temp:") or "looker" in k.lower()) and v and isinstance(v, str):
                logger.info(f"Looker token dynamically resolved from tool_context.state matching key: {k}")
                return v

    # 2. Check session.state
    if tool_context and hasattr(tool_context, "session"):
        session = getattr(tool_context, "session", None)
        if session and hasattr(session, "state") and isinstance(session.state, dict):
            for k in candidate_keys:
                if k and k in session.state and session.state[k]:
                    logger.info(f"Looker token resolved from session.state key: {k}")
                    return str(session.state[k])
            for k, v in session.state.items():
                if (k.startswith("temp:") or "looker" in k.lower()) and v and isinstance(v, str):
                    logger.info(f"Looker token dynamically resolved from session.state matching key: {k}")
                    return v

    # 3. Environment override
    if settings.looker_a2a_token:
        logger.info("Using LOOKER_A2A_TOKEN from environment.")
        return settings.looker_a2a_token

    # 4. Developer local fallbacks
    cli_token = _get_token_from_looker_cli()
    if cli_token:
        logger.info("Using token from looker-cli config for local execution.")
        return cli_token

    cred_token = _get_token_from_client_credentials()
    if cred_token:
        logger.info("Using token obtained via client credentials.")
        return cred_token

    logger.warning("No Looker access token could be resolved from context or environment.")
    return None
