import json

import msal
import requests

TENANT_ID = "<tenant-id>"
PUBLIC_CLIENT_APP_ID = "<public-client-app-id>"
APIM_API_APP_ID = "<apim-api-app-client-id>"
APIM_URL = "https://<your-apim-name>.azure-api.net/foundry/chat/completions"


def get_user_access_token() -> str:
    app = msal.PublicClientApplication(
        client_id=PUBLIC_CLIENT_APP_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    )

    flow = app.initiate_device_flow(
        scopes=[f"api://{APIM_API_APP_ID}/user_impersonation"]
    )
    if "user_code" not in flow:
        raise RuntimeError("Failed to start device code flow.")

    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(
            "Interactive sign-in failed: "
            f"{result.get('error')} - {result.get('error_description')}"
        )

    return result["access_token"]


response = requests.post(
    APIM_URL,
    headers={
        "Authorization": f"Bearer {get_user_access_token()}",
        "Content-Type": "application/json",
    },
    json={
        "model": "<model-name>",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What are the top 3 most popular colors?"},
        ],
    },
    timeout=15,
)

response.raise_for_status()
print(json.dumps(response.json(), indent=2))