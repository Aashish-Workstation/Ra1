from infisical_sdk import InfisicalSDKClient
import os

_client = None

def get_infisical_client() -> InfisicalSDKClient:
    global _client
    if _client is None:
        host = os.environ.get("INFISICAL_HOST", "https://app.infisical.com")
        _client = InfisicalSDKClient(host=host)
        _client.auth.universal_auth.login(
            client_id=os.environ["INFISICAL_MACHINE_CLIENT_ID"],
            client_secret=os.environ["INFISICAL_MACHINE_CLIENT_SECRET"],
        )
    return _client

def get_secret(key: str, environment: str = "development") -> str:
    client = get_infisical_client()
    secret = client.secrets.get_secret_by_name(
        secret_name=key,
        project_id=os.environ["INFISICAL_PROJECT_ID"],
        environment_slug=environment,
    )
    return secret.secretKey

def set_secret(key: str, value: str, environment: str = "development") -> None:
    client = get_infisical_client()
    client.secrets.create_secret_by_name(
        secret_name=key,
        secret_value=value,
        project_id=os.environ["INFISICAL_PROJECT_ID"],
        environment_slug=environment,
    )