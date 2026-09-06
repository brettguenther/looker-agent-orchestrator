from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices
from typing import Optional

class Settings(BaseSettings):
    google_cloud_project: str = Field(default="your-gcp-project-id", alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(default="us-central1", alias="GOOGLE_CLOUD_LOCATION")
    project_number: Optional[str] = Field(default=None, alias="PROJECT_NUMBER")
    gemini_enterprise_app_id: Optional[str] = Field(default="", alias="GEMINI_ENTERPRISE_APP_ID")
    
    # Looker Instance & Domain Agents
    looker_base_url: str = Field(default="https://your-instance.cloud.looker.com", alias="LOOKER_BASE_URL")
    
    # Domain Agent 1 (e.g. Sales, Financials, Customer Operations)
    looker_agent_1_name: str = Field(default="Domain Agent 1", alias="LOOKER_AGENT_1_NAME")
    looker_agent_1_description: str = Field(
        default="Queries the primary business domain for analytical metrics and insights.",
        alias="LOOKER_AGENT_1_DESCRIPTION",
    )
    looker_agent_1_uuid: str = Field(
        default="your-agent-1-uuid",
        validation_alias=AliasChoices("LOOKER_AGENT_1_UUID", "LOOKER_SALES_AGENT_UUID"),
    )

    # Domain Agent 2 (e.g. Web Traffic, Marketing Channels, Inventory)
    looker_agent_2_name: str = Field(default="Domain Agent 2", alias="LOOKER_AGENT_2_NAME")
    looker_agent_2_description: str = Field(
        default="Queries the secondary business domain for analytical metrics and insights.",
        alias="LOOKER_AGENT_2_DESCRIPTION",
    )
    looker_agent_2_uuid: str = Field(
        default="your-agent-2-uuid",
        validation_alias=AliasChoices("LOOKER_AGENT_2_UUID", "LOOKER_TRAFFIC_AGENT_UUID"),
    )

    # Backward compatibility properties
    @property
    def looker_sales_agent_uuid(self) -> str:
        return self.looker_agent_1_uuid

    @property
    def looker_traffic_agent_uuid(self) -> str:
        return self.looker_agent_2_uuid

    # OAuth Authorization in Gemini Enterprise
    looker_auth_id: str = Field(default="looker-orchestrator-auth", alias="LOOKER_AUTH_ID")
    auth_id_resource: Optional[str] = Field(default="", alias="AUTH_ID_RESOURCE")
    
    # Local Dev Token fallback
    looker_a2a_token: Optional[str] = Field(default=None, alias="LOOKER_A2A_TOKEN")
    model_name: str = Field(default="gemini-2.5-flash", alias="MODEL_NAME")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
