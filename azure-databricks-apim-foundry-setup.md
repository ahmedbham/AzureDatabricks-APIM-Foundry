# Azure Databricks to Foundry via APIM Setup

This guide covers the Azure Databricks workspace flow for calling Azure AI Foundry through Azure API Management (APIM). In this pattern, APIM fronts the Foundry endpoint and authenticates to the backend by using its managed identity.

For the Mosaic AI custom serving pattern that uses an APIM subscription key stored in a Databricks secret, see [databricks-mosaic-to-foundry-via-apim.md](databricks-mosaic-to-foundry-via-apim.md).

## Architecture Diagram

The architecture diagram is available as an editable draw.io file at [diagrams/adb-apim-foundry-architecture.drawio](diagrams/adb-apim-foundry-architecture.drawio).

**Viewing:** Open in [draw.io](https://app.diagrams.net/) (web) or the draw.io VS Code extension. The diagram has three toggleable layers:
- **Infrastructure Components**: VNets, subnets, Azure resources (APIM, Databricks, Foundry, Entra ID)
- **Network Connectivity**: Private Endpoint connections and network injection
- **Access Control**: Role assignments, app registrations, APIM inbound policies, and auth flow

**Exporting to PNG/SVG:** In draw.io, go to *File -> Export as -> PNG/SVG*. Select "All Pages" and enable "Include a copy of my diagram" to keep it editable.

## VNet

1. Create a VNet with the following subnets:
   - `PE Subnet` for Private Endpoint.
   - `APIM Subnet` for APIM subnet delegation. This subnet must have an associated Network Security Group.

## Microsoft Foundry

1. Create a Private Endpoint for Microsoft Foundry in the `PE Subnet` of the VNet created in step 1.

## Azure API Management

1. Create an APIM instance with the following settings:
   - `Premium V2` SKU
   - Network configuration:
     - `Network Integration`
     - Optional: `APIM Subnet` for subnet delegation
   - Managed identity enabled
2. Optional: Create a Private Endpoint for APIM in the `PE Subnet` of the VNet for Azure Databricks public subnet access.
3. Import Microsoft Foundry APIs into APIM:
   - Under `Client Compatibility`, use the OpenAI v1 option.
   - Under `APIs -> APIs -> {Foundry API} -> Settings`:
     - In `API URL Suffix`, remove any `/openai/v1` fragment.
     - Uncheck `Subscription required` to allow calls without a subscription key for this workspace-identity flow.
4. Under `APIs -> APIs -> {Foundry API} -> All operations -> Inbound Processing -> Policies`, add the following policy to the `inbound` section so APIM acquires a managed identity token and forwards it to the Foundry backend:

```xml
<!-- 1. Acquire token for the Managed Identity -->
<!-- Use "https://cognitiveservices.azure.com/" for Azure OpenAI models -->
<authentication-managed-identity resource="https://cognitiveservices.azure.com/" output-token-variable-name="msi-access-token" ignore-error="false" />
<!-- 2. Set the Authorization header for the backend -->
<set-header name="Authorization" exists-action="override">
    <value>@("Bearer " + (string)context.Variables["msi-access-token"])</value>
</set-header>
```

## Azure Databricks

1. Ensure either the APIM private endpoint is created in the same VNet or the APIM subnet is delegated into the same network design used by Azure Databricks.
2. In a notebook, add the following code to call the APIM endpoint for Microsoft Foundry:

```python
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
```

## Authorize APIM Calls with Azure Databricks Workspace Managed Identity

### Create an Entra app registration for APIM

1. In the Azure portal, navigate to `Azure Active Directory -> App registrations -> New registration`.
2. Name the app, for example `APIM Access for Databricks`, and register it.
3. Set `Application ID URI` to `api://{client-id}`, where `{client-id}` is the application client ID for the app registration. This is the audience Databricks will request.
4. Note the `Application (client) ID` as `APP_ID` and the `Directory (tenant) ID` as `TENANT_ID`.
5. Create app roles for the app registration:
   - Under the app registration, open `App roles` and choose `Create app role`.
   - Set allowed member types to `Application` and record both the role value `APP_ROLE_VALUE` and the app role ID `APP_ROLE_ID`.
6. Under `Enterprise applications`, find the app registration created in step 1 and note its object ID as `API_SP_ID`.

### Assign the app role to the Azure Databricks workspace managed identity

1. Option A:
   - In the Azure portal, navigate to `Managed Identities`.
   - Find the managed identity named `dbmanagedidentity`.
   - Note its object ID as `CALLER_OID`.
2. Option B, if the managed identity is not visible in the portal:

```python
import jwt

from azure.identity import ManagedIdentityCredential

credential = ManagedIdentityCredential()
access_token = credential.get_token(API_AUDIENCE)

token = access_token.token

decoded = jwt.decode(token, options={"verify_signature": False})

print(decoded.get("oid"))
```

3. Note the output from the notebook as `CALLER_OID`.
4. In Cloud Shell, assign the app role to the managed identity:

```bash
az rest \
  --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$CALLER_OID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{\"principalId\":\"$CALLER_OID\",\"resourceId\":\"$API_SP_OID\",\"appRoleId\":\"$APP_ROLE_ID\"}"
```

### Configure APIM to validate the token from Azure Databricks

1. In the APIM instance, open the API for Microsoft Foundry.
2. Update the inbound policy to validate the Entra token and enforce the app role assignment:

```xml
<!-- 1. Validate Entra ID issued JWT -->
<validate-jwt header-name="Authorization" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized" require-scheme="Bearer" output-token-variable-name="jwt">
    <openid-config url="https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration" />
    <audiences>
        <audience>{APP_ID}</audience>
    </audiences>
    <issuers>
        <issuer>https://login.microsoftonline.com/{TENANT_ID}/v2.0</issuer>
    </issuers>
    <required-claims>
        <claim name="roles" match="any">
            <value>{APP_ROLE_VALUE}</value>
        </claim>
    </required-claims>
</validate-jwt>
```

### Test the setup from Azure Databricks

```python
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
```

## Authorize APIM Calls with a Service Principal

### Create an Entra app registration for the service principal

Create an app registration for the caller service principal, named `adb-client-app` in this example.

### Assign the app role to the service principal

1. Get `CALLER_OID` for `adb-client-app`:

```bash
CALLER_OID=$(az ad sp list \
  --filter "displayName eq 'adb-client-app'" \
  --query "[0].id" -o tsv)
echo $CALLER_OID
```

2. Get `API_SP_OID` for `apim-api-app`:

```bash
API_SP_OID=$(az ad sp list \
  --filter "displayName eq 'apim-api-app'" \
  --query "[0].id" -o tsv)
echo $API_SP_OID
```

3. Perform the app role assignment:

```bash
az rest \
  --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$CALLER_OID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{
    \"principalId\": \"$CALLER_OID\",
    \"resourceId\": \"$API_SP_OID\",
    \"appRoleId\": \"$APP_ROLE_ID\"
  }"
```

### Test the setup from Azure Databricks

```python
%pip install msal
dbutils.library.restartPython()
import msal
import requests

TENANT_ID = "<your-tenant-id>"
ADB_CLIENT_APP_ID = "<adb-client-app-client-id>"
APIM_API_APP_CLIENT_ID = "<apim-api-app-client-id>"

SCOPE = [f"api://{APIM_API_APP_CLIENT_ID}/.default"]

CLIENT_SECRET = dbutils.secrets.get(scope="<scope-name>", key="<adb-client-app-client-secret-key>")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

app = msal.ConfidentialClientApplication(
    client_id=ADB_CLIENT_APP_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

result = app.acquire_token_for_client(scopes=SCOPE)

if "access_token" not in result:
    raise Exception(
        f"Token acquisition failed: {result.get('error')} - {result.get('error_description')}"
    )

access_token = result["access_token"]
print("Got access token (length):", len(access_token))
```