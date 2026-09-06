import asyncio
import os
import sys
import subprocess
from dotenv import load_dotenv

# Load .env before initializing any ADK or GenAI modules
load_dotenv()
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id")
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Monkey-patch google.auth.default so local dev uses active gcloud credentials
import google.auth
from google.auth.credentials import Credentials

class GCloudUserCredentials(Credentials):
    def __init__(self):
        super().__init__()
        self.refresh(None)
    def refresh(self, request):
        self.token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()

_orig_default = google.auth.default
google.auth.default = lambda *args, **kwargs: (GCloudUserCredentials(), project_id)

from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

# Ensure current directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agent import root_agent

async def run_query(prompt: str):
    print(f"\n==========================================")
    print(f"User Query: {prompt}")
    print(f"==========================================\n")
    
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="looker_orchestrator",
        user_id="test_analyst",
        session_id="local_test_session"
    )
    
    runner = Runner(
        agent=root_agent,
        session_service=session_service,
        app_name="looker_orchestrator"
    )
    
    print("Executing Orchestrator with Runner...")
    async for event in runner.run_async(
        session_id=session.id,
        user_id="test_analyst",
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)])
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    print(part.text, end="", flush=True)
                elif getattr(part, "function_call", None):
                    print(f"\n[Tool Call] -> {part.function_call.name}({part.function_call.args})")
                elif getattr(part, "function_response", None):
                    print(f"\n[Tool Response Received] len={len(str(part.function_response.response))}")
        if event.error_message:
            print(f"\n[Error]: {event.error_message}")
            
    print("\n\nExecution Complete!")

if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else "What are the key performance metrics from our Looker models?"
    asyncio.run(run_query(prompt))
