# Instructions for use

## Architecture Diagram

The architecture diagram is available as an editable draw.io file at [`diagrams/architecture.drawio`](diagrams/architecture.drawio).

**Viewing:** Open in [draw.io](https://app.diagrams.net/) (web) or the draw.io VS Code extension. The diagram has three toggleable layers:
- **Infrastructure Components** — VNets, subnets, Azure resources (APIM, Databricks, Foundry, Entra ID)
- **Network Connectivity** — Private Endpoint connections and network injection
- **Access Control** — Role assignments, app registrations, APIM inbound policies, and auth flow

**Exporting to PNG/SVG:** In draw.io, go to *File → Export as → PNG/SVG*. Select "All Pages" and enable "Include a copy of my diagram" to keep it editable.

---

## VNet
1. Create a VNet with the following subnets:
   - `PE Subnet` (for Private Endpoint)
   - `APIM Subnet` (for APIM subnet delegation; must have an associated Network Security Group)
## Microsoft Foundry
1. Create a Private Endpoint for Microsoft Foundry in the `PE Subnet` of the VNet created in step 1.

## Azure API Management (APIM)
1. Create an APIM instance with following settings:
   - `Premium V2` SKU
   - Network configuration:
     - `Network Integration` 
     - [Optional] `APIM Subnet` for subnet delegation
   - Managed Identity enabled
2. [Optional] Create a Private Endpoint for APIM in the `PE Subnet` of the VNet for Azure Databricks public subnet access.
3. Import Microsoft Foundry APIs into APIM:
    - Under `Client Compatibility` Use OpenAI v1 Option
    - under APIs --> APIs --> {Foundry API} --> Settings --> API URL Suffix, remove any `/openai/v1` from the API URL Suffix field. 
4. under APIs --> APIs --> {Foundry API} --> All operations --> Inbound Processing --> Policies:
   - Add the following policy to the `inbound` section to acquire a token for the Managed Identity and set the Authorization header for the backend API calls to Microsoft Foundry. 
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
1. Ensure either APIM PE is created in the same VNet or APIM Subnet is delegated to the same VNet as Azure Databricks.
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

## Authorizing call to APIM with Azure Databricks Workspace Managed Identity
### Create an Azure AD App Registration for APIM
1. In the Azure portal, navigate to Azure Active Directory --> App registrations --> New registration.
2. Name the app (e.g., "APIM Access for Databricks") and register it.
3. Set "Application ID URI" to a "api://{client-id}" where {client-id} is the Application (client) ID ("APP_ID") of the app registration. This will be used as the audience for the token request from Databricks.
4. Note down the "Application (client) ID" ("APP_ID") and "Directory (tenant) ID" ("TENANT_ID") for the app registration created.
5. Create App Roles for the app registration:
   - Under the app registration, go to "App roles" --> "Create app role".
   - Name the role (e.g., "MyApi.Invoke"), set allowed member types to "Application", and provide a value (e.g., "MyApi.Invoke") and a Descrption (e.g. "allow ADB MI to access APIM API").
   - Note down the app role value ("APP_ROLE_VALUE") and the App Role ID ("APP_ROLE_ID") for the role created.
6. Under "Enterprises applications", find the app registration created in step 1 and click on it.
   - Note down the "Object ID" ("API_SP_ID").
### Assign the App Role to the Azure Databricks Workspace Managed Identity
1. Option A
   - In the Azure portal, navigate to the Managed Identities.
    - Find the Managed Identity named "dbmanagedidentity".
    - Note down the Object ID of the Managed Identity ("CALLER_OID").
2. Option B (if the Managed Identity is not visible in the portal)
   -  In a notebook, execute the following code to get the Object ID of the Managed Identity:
    ```python
    import jwt

    from azure.identity import ManagedIdentityCredential

    credential = ManagedIdentityCredential()
    access_token = credential.get_token(API_AUDIENCE)

    token = access_token.token

    decoded = jwt.decode(token, options={"verify_signature": False})

    print(decoded.get("oid"))
   ```
   - Note down the output, which is the Object ID of the Managed Identity ("CALLER_OID").
   - In Cloud Shell, assign the app role to the Managed Identity using the following command:
   ```bash
   az rest \
  --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$CALLER_OID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{\"principalId\":\"$CALLER_OID\",\"resourceId\":\"$API_SP_OID\",\"appRoleId\":\"$APP_ROLE_ID\"}"
    ```
### Configure APIM to validate the token from Azure Databricks
1. In the APIM instance, navigate to the API for Microsoft Foundry.
2. Update the inbound policy to include the following policy to validate the token from Azure Databricks and check for the app role assignment:
```xml
<!-- 1️⃣ Validate Entra ID issued JWT -->
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
### Test the setup by executing a notebook in Azure Databricks. 
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

## Authorizing call to APIM with a Service Principal 
### Create an Azure AD App Registration for the Service Principal ('adb-client-app' in this example)
### Assign the App Role to the Service Principal
1. Get CALLER_OID for adb-client-app (client service principal object id)
```bash
CALLER_OID=$(az ad sp list \
  --filter "displayName eq 'adb-client-app'" \
  --query "[0].id" -o tsv)
echo $CALLER_OID
```
2. Get API_SP_OID for apim-api-app (resource/API service principal object id)
```bash
API_SP_OID=$(az ad sp list \
  --filter "displayName eq 'apim-api-app'" \
  --query "[0].id" -o tsv)
echo $API_SP_OID
```
3. Perform the app role assignment using the following command:
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
### Test the setup by executing a notebook in Azure Databricks. 
```python
%pip install msal
dbutils.library.restartPython()
import msal
import requests

# -----------------------------
# REQUIRED SETTINGS
# -----------------------------
TENANT_ID = "<your-tenant-id>"  # GUID or contoso.onmicrosoft.com
ADB_CLIENT_APP_ID = "<adb-client-app-client-id>"
APIM_API_APP_CLIENT_ID = "<apim-api-app-client-id>"

# Your requested audience/scope (client-credentials uses ".default")
SCOPE = [f"api://{APIM_API_APP_CLIENT_ID}/.default"]  # must be a list for MSAL

# Databricks secrets (recommended)
# Store your client secret in a secret scope/key
CLIENT_SECRET = dbutils.secrets.get(scope="<scope-name>", key="<adb-client-app-client-secret-key>")

# Authority must be https://login.microsoftonline.com/{tenant}
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# -----------------------------
# MSAL CONFIDENTIAL CLIENT
# -----------------------------
app = msal.ConfidentialClientApplication(
    client_id=ADB_CLIENT_APP_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

# Acquire app-only token
result = app.acquire_token_for_client(scopes=SCOPE)

if "access_token" not in result:
    raise Exception(
        f"Token acquisition failed: {result.get('error')} - {result.get('error_description')}"
    )

access_token = result["access_token"]
print("✅ Got access token (length):", len(access_token))
```