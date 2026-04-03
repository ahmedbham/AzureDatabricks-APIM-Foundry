import json

import msal
import requests


TENANT_ID = "<tenant-id>"
APIM_API_APP_ID = "<apim-api-app-client-id>"
OBO_CLIENT_APP_ID = "<adb-obo-client-app-client-id>"
APIM_URL = "https://<your-apim-name>.azure-api.net/foundry/chat/completions"

CLIENT_SECRET = dbutils.secrets.get(
    scope="<scope-name>",
    key="<adb-obo-client-app-secret-key>",
)


def get_user_assertion() -> str:
    """
    Supply an upstream Entra user token here.

    In production, obtain this from a trusted client or token broker that already
    authenticated the user. A Databricks notebook does not mint this assertion by itself.
    This sample uses a widget only to make the dependency explicit.
    """
    token = dbutils.widgets.get("user_assertion")
    if not token:
        raise ValueError("The user_assertion widget is empty.")
    return token


app = msal.ConfidentialClientApplication(
    client_id=OBO_CLIENT_APP_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    client_credential=CLIENT_SECRET,
)

obo_result = app.acquire_token_on_behalf_of(
    user_assertion=get_user_assertion(),
    scopes=[f"api://{APIM_API_APP_ID}/user_impersonation"],
)

if "access_token" not in obo_result:
    raise RuntimeError(
        "OBO token acquisition failed: "
        f"{obo_result.get('error')} - {obo_result.get('error_description')}"
    )

response = requests.post(
    APIM_URL,
    headers={
        "Authorization": f"Bearer {obo_result['access_token']}",
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