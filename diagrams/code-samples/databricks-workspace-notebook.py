from azure.identity import ManagedIdentityCredential
import jwt
import json
import requests

cred = ManagedIdentityCredential()  # uses the identity available on this compute
token = cred.get_token("api://{APP_ID}/.default").token

apim_url = "https://{your-apim-name}.azure-api.net/foundry/chat/completions"
headers = {
  "Authorization": f"Bearer {token}",
  "Content-Type": "application/json"
}

data = {
    "model": "{model-name}", 
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "what are the top 3 most popular colors"}
    ]
}

try:
    # We add a timeout because VNet/DNS issues can cause long hangs
    response = requests.post(apim_url, headers=headers, json=data, timeout=15)
    
    # Check for HTTP errors (401, 404, 500, etc.)
    response.raise_for_status()
    
    print("Success! Response from AI Foundry:")
    print(json.dumps(response.json(), indent=2))

except requests.exceptions.ConnectionError:
    print("Connection Error: Databricks cannot reach the APIM URL. Check VNet peering and DNS.")
except requests.exceptions.HTTPError as e:
    print(f"HTTP Error: {e}")
    print(f"Backend details: {response.text}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")