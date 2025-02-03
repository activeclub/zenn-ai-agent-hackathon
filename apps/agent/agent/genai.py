from google import genai

from agent.config import config

genai_client = genai.client.Client(
    api_key=config.gemini_api_key,
    http_options={"api_version": "v1alpha"},
)
