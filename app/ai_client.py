import os
from openai import OpenAI, AzureOpenAI
from dotenv import load_dotenv

load_dotenv()


def get_client() -> OpenAI:
    """Create OpenAI or Azure OpenAI client based on environment config."""
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    if azure_key:
        return AzureOpenAI(
            api_key=azure_key,
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        )
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_model() -> str:
    """Get the model/deployment name to use."""
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if azure_deployment:
        return azure_deployment
    return os.getenv("MODEL_NAME", "gpt-4")
