# Azure Databricks to Foundry via APIM Setup

This guide covers the Azure Databricks notebook flow for calling Azure AI Foundry through Azure API Management (APIM). APIM fronts the Foundry endpoint, validates Microsoft Entra tokens from the Databricks-side caller, and then authenticates to the Foundry backend by using its managed identity.

The primary pattern in this document is interactive notebook access that uses an On-Behalf-Of (OBO) token to call an Entra-protected APIM endpoint. The document also keeps the existing app-only alternatives for scheduled or unattended workloads:

- OBO delegated user flow: interactive notebook access on behalf of a signed-in user.
- Workspace managed identity flow: app-only token issued to the Databricks compute identity.
- Service principal flow: app-only token issued to a confidential client.

For the Mosaic AI custom serving pattern that uses an APIM subscription key stored in a Databricks secret, see [databricks-mosaic-to-foundry-via-apim.md](databricks-mosaic-to-foundry-via-apim.md).

## What This Guide Implements

- Entra-protected APIM endpoint for Azure Databricks callers.
- APIM managed identity authentication to Azure AI Foundry.
- OBO token exchange from a Databricks notebook.
- Optional app-only access with Databricks managed identity or a service principal.
- APIM policy examples for validating caller tokens and forwarding requests to Foundry.

## Important OBO Requirement

True OBO requires a user assertion token that represents the signed-in user. In practice, the notebook needs an upstream Entra token from a trusted client or token broker. Azure Databricks notebooks do not mint that upstream Entra user assertion for you automatically.

Use OBO only when all of the following are true:

- The notebook runs in an interactive user context.
- You already have a user access token issued by Entra ID for an upstream application.
- The notebook can securely receive that user assertion and exchange it by using a confidential client.

If those conditions are not true, use the managed identity or service principal sections later in this document instead of forcing an OBO design.

## Architecture Diagram

The architecture diagram is available as an editable draw.io file at [diagrams/adb-apim-foundry-architecture.drawio](diagrams/adb-apim-foundry-architecture.drawio).

**Viewing:** Open in [draw.io](https://app.diagrams.net/) (web) or the draw.io VS Code extension. The diagram has three toggleable layers:
- **Infrastructure Components**: VNets, subnets, Azure resources (APIM, Databricks, Foundry, Entra ID)
- **Network Connectivity**: Private Endpoint connections and network injection
- **Access Control**: Role assignments, app registrations, APIM inbound policies, and auth flow

**Exporting to PNG/SVG:** In draw.io, go to *File -> Export as -> PNG/SVG*. Select "All Pages" and enable "Include a copy of my diagram" to keep it editable.

## Target Flow

For the OBO path, the intended request flow is:

1. A user signs in with Entra ID to an upstream client or broker that can supply a user assertion.
2. The Databricks notebook uses that user assertion with a confidential client and performs an OBO exchange for the APIM API audience.
3. The notebook calls APIM with the OBO access token.
4. APIM validates the delegated token.
5. APIM acquires its own managed identity token for `https://cognitiveservices.azure.com/`.
6. APIM forwards the request to the Azure AI Foundry backend.

For app-only alternatives, steps 1 and 2 are replaced by managed identity token acquisition or client credentials token acquisition.

## Prerequisites

- An Azure Databricks workspace.
- An Azure AI Foundry project or endpoint with a deployed chat-capable model.
- An APIM instance that can reach Azure AI Foundry.
- APIM managed identity enabled.
- Permission to create Entra app registrations or work with an identity admin.
- Permission to create Databricks secrets if you use the OBO confidential client or service principal options.
- Network connectivity that allows Databricks to reach the APIM gateway and APIM to reach the Foundry endpoint.

## VNet

1. Create a VNet with the following subnets:
   - `PE Subnet` for private endpoints.
   - `APIM Subnet` for APIM subnet delegation if you use APIM network integration. This subnet must have an associated Network Security Group.
2. Ensure your DNS design resolves the APIM gateway hostname and the Foundry private endpoint hostname to the expected private addresses if public access is disabled.

## Microsoft Foundry

1. Deploy the target chat model in Azure AI Foundry.
2. Create a private endpoint for Microsoft Foundry in the `PE Subnet` if you want private backend access from APIM.
3. Grant the APIM managed identity the Azure role required to invoke the Foundry endpoint. For Azure AI services-backed model endpoints, this is typically the appropriate Cognitive Services or Azure AI user role for inference.

## Microsoft Entra ID Configuration

### 1. Create the APIM API app registration

Create an app registration that represents the APIM-protected API. This registration is the audience that Databricks-side callers request.

1. In the Azure portal, go to `Microsoft Entra ID -> App registrations -> New registration`.
2. Name the app, for example `apim-api-app`.
3. Note the following values:
   - `APIM_API_APP_ID`: the application (client) ID.
   - `TENANT_ID`: the directory (tenant) ID.
4. Under `Expose an API`, set the Application ID URI to `api://{APIM_API_APP_ID}`.
5. Add a delegated scope named `user_impersonation`.
6. Recommended: create an app role such as `Foundry.Invoke`.
    - For delegated user flows, allow member types `Users/Groups` and assign the role to the specific Entra groups that are allowed to call APIM.
    - For app-only flows, allow member type `Applications` if you also want service principals or managed identities to call the same API surface.
7. Under `Enterprise applications`, find the service principal for this app and note its object ID as `API_SP_ID`.

For delegated OBO calls, APIM validates the `scp` claim and expects `user_impersonation`.

For delegated group-restricted OBO calls, APIM should validate both the delegated scope and the app role claim. The role is assigned to Entra groups through the enterprise application, so only members of those groups receive the role in their token.

For app-only calls, APIM validates the `roles` claim and expects the app role value such as `Foundry.Invoke`.

### Delegated group or app-role restriction

If you need to restrict notebook access to specific Entra groups, prefer app roles assigned to groups over direct `groups` claim checks.

1. In the APIM API app registration, define an app role such as `Foundry.Invoke` with allowed member type `Users/Groups`.
2. In `Enterprise applications -> apim-api-app -> Properties`, set `Assignment required?` to `Yes`.
3. In `Users and groups`, assign only the allowed Entra groups to the app role.
4. Keep the delegated permission `user_impersonation` on the client application.
5. In APIM, require both `scp=user_impersonation` and `roles=Foundry.Invoke`.

This pattern is more reliable than checking raw `groups` claims directly because it avoids common group overage issues in large tenants and is easier to audit.

### 2. Create the confidential client for OBO

Create a second app registration that the notebook uses to perform the OBO exchange.

1. Create an app registration, for example `adb-obo-client-app`.
2. Create a client secret or certificate credential.
3. Add an API permission to `apim-api-app`:
   - Type: `Delegated permissions`
   - Permission: `user_impersonation`
4. Grant admin consent for the delegated permission.
5. Store the secret or certificate reference securely. In Databricks, use a secret scope rather than hardcoding a secret in the notebook.

## Azure API Management

1. Create an APIM instance with the following settings:
   - `Premium v2` SKU for private networking scenarios.
   - Network configuration:
     - `Network Integration`
     - Optional: `APIM Subnet` for subnet delegation
   - Managed identity enabled
2. Optional: create a private endpoint for APIM in the `PE Subnet` if Databricks reaches APIM privately.
3. Import the Microsoft Foundry APIs into APIM:
   - Under `Client Compatibility`, use the OpenAI v1 option.
   - Under `APIs -> APIs -> {Foundry API} -> Settings`:
     - In `API URL Suffix`, remove any extra `/openai/v1` fragment.
     - Uncheck `Subscription required` when caller authentication is done with Entra ID instead of APIM subscription keys.

### APIM inbound policy for the OBO flow

Validate the incoming delegated token first. Only after that should APIM overwrite the backend `Authorization` header with its own managed identity token for Foundry.

```xml
<policies>
    <inbound>
        <base />

        <validate-jwt header-name="Authorization"
                      require-scheme="Bearer"
                      failed-validation-httpcode="401"
                      failed-validation-error-message="Unauthorized"
                      output-token-variable-name="caller-jwt">
            <openid-config url="https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration" />
            <audiences>
                <audience>{APIM_API_APP_ID}</audience>
            </audiences>
            <issuers>
                <issuer>https://login.microsoftonline.com/{TENANT_ID}/v2.0</issuer>
            </issuers>
            <required-claims>
                <claim name="scp" match="all">
                    <value>user_impersonation</value>
                </claim>
            </required-claims>
        </validate-jwt>

        <authentication-managed-identity resource="https://cognitiveservices.azure.com/"
                                         output-token-variable-name="msi-access-token"
                                         ignore-error="false" />

        <set-header name="Authorization" exists-action="override">
            <value>@("Bearer " + (string)context.Variables["msi-access-token"])</value>
        </set-header>

        <set-backend-service id="apim-generated-policy" backend-id="aif-foundry-ai-endpoint" />
    </inbound>
    <backend>
        <base />
    </backend>
    <outbound>
        <base />
    </outbound>
    <on-error>
        <base />
    </on-error>
</policies>
```

### APIM inbound policy for delegated users restricted by Entra groups

If only specific user groups should be allowed through the delegated notebook flow, require the delegated scope and an app role claim in the same token. The app role is assigned to the allowed Entra groups on the enterprise application.

```xml
<policies>
    <inbound>
        <base />

        <validate-jwt header-name="Authorization"
                      require-scheme="Bearer"
                      failed-validation-httpcode="401"
                      failed-validation-error-message="Unauthorized"
                      output-token-variable-name="caller-jwt">
            <openid-config url="https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration" />
            <audiences>
                <audience>{APIM_API_APP_ID}</audience>
            </audiences>
            <issuers>
                <issuer>https://login.microsoftonline.com/{TENANT_ID}/v2.0</issuer>
            </issuers>
            <required-claims>
                <claim name="scp" match="all">
                    <value>user_impersonation</value>
                </claim>
                <claim name="roles" match="any">
                    <value>Foundry.Invoke</value>
                </claim>
            </required-claims>
        </validate-jwt>

        <authentication-managed-identity resource="https://cognitiveservices.azure.com/"
                                         output-token-variable-name="msi-access-token"
                                         ignore-error="false" />

        <set-header name="Authorization" exists-action="override">
            <value>@("Bearer " + (string)context.Variables["msi-access-token"])</value>
        </set-header>

        <set-backend-service id="apim-generated-policy" backend-id="aif-foundry-ai-endpoint" />
    </inbound>
    <backend>
        <base />
    </backend>
    <outbound>
        <base />
    </outbound>
    <on-error>
        <base />
    </on-error>
</policies>
```

Notes:

- The critical ordering is `validate-jwt` first, then `authentication-managed-identity`, then `set-header`. If you overwrite `Authorization` before validation, APIM validates its own backend token instead of the caller token.
- Use the value that actually appears in the `aud` claim of your APIM access token. For most Entra custom APIs this is the API application's client ID.
- For delegated user restrictions, prefer app roles assigned to groups over validating raw `groups` claims directly. Raw group claims can hit Entra group overage limits and may not be present in the token.
- If you want one API surface to accept both delegated and app-only tokens, either use separate APIM products or operations, or add conditional policy logic. Separate policies are simpler to audit.

### APIM inbound policy for app-only callers

If the caller is a managed identity or service principal, validate the app role instead of the delegated scope:

```xml
<validate-jwt header-name="Authorization"
              require-scheme="Bearer"
              failed-validation-httpcode="401"
              failed-validation-error-message="Unauthorized"
              output-token-variable-name="caller-jwt">
    <openid-config url="https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration" />
    <audiences>
        <audience>{APIM_API_APP_ID}</audience>
    </audiences>
    <issuers>
        <issuer>https://login.microsoftonline.com/{TENANT_ID}/v2.0</issuer>
    </issuers>
    <required-claims>
        <claim name="roles" match="any">
            <value>Foundry.Invoke</value>
        </claim>
    </required-claims>
</validate-jwt>
```

## Azure Databricks Notebook: OBO Flow

This sample shows the notebook performing an OBO exchange and then calling APIM with the resulting delegated access token.

```python
%pip install msal requests
dbutils.library.restartPython()
```

```python
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

apim_token = obo_result["access_token"]

payload = {
    "model": "<model-name>",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What are the top 3 most popular colors?"},
    ],
}

response = requests.post(
    APIM_URL,
    headers={
        "Authorization": f"Bearer {apim_token}",
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=15,
)

response.raise_for_status()
print(json.dumps(response.json(), indent=2))
```

Use this OBO sample only when the notebook truly acts on behalf of a user. For scheduled jobs, job clusters, or service-to-service calls, use one of the app-only patterns below.

## Azure Databricks Notebook: Workspace Managed Identity Flow

This repo already includes a workspace managed identity sample in [diagrams/code-samples/databricks-workspace-notebook.py](diagrams/code-samples/databricks-workspace-notebook.py). Use this pattern when the Databricks compute identity is the caller.

### Assign the app role to the Azure Databricks managed identity

1. In the Azure portal, locate the Databricks managed identity and note its object ID as `CALLER_OID`.
2. If needed, decode an access token in a notebook to confirm the object ID:

```python
import jwt
from azure.identity import ManagedIdentityCredential

credential = ManagedIdentityCredential()
access_token = credential.get_token("api://{APIM_API_APP_ID}/.default")
decoded = jwt.decode(access_token.token, options={"verify_signature": False})

print(decoded.get("oid"))
```

3. Assign the app role to the managed identity:

```bash
az rest \
  --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$CALLER_OID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{\"principalId\":\"$CALLER_OID\",\"resourceId\":\"$API_SP_ID\",\"appRoleId\":\"$APP_ROLE_ID\"}"
```

### Call APIM from the notebook with managed identity

```python
from azure.identity import ManagedIdentityCredential
import json
import requests

cred = ManagedIdentityCredential()
token = cred.get_token("api://{APIM_API_APP_ID}/.default").token

apim_url = "https://{your-apim-name}.azure-api.net/foundry/chat/completions"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}

data = {
    "model": "{model-name}",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What are the top 3 most popular colors?"},
    ],
}

response = requests.post(apim_url, headers=headers, json=data, timeout=15)
response.raise_for_status()
print(json.dumps(response.json(), indent=2))
```

## Authorize APIM Calls with a Service Principal

Use this pattern when the Databricks notebook or job runs under a dedicated confidential client instead of a managed identity.

### Create the caller app registration

Create an app registration for the caller service principal, named `adb-client-app` in this example, and store its secret in a Databricks secret scope.

### Assign the app role to the service principal

1. Get `CALLER_OID` for `adb-client-app`:

```bash
CALLER_OID=$(az ad sp list \
  --filter "displayName eq 'adb-client-app'" \
  --query "[0].id" -o tsv)
echo $CALLER_OID
```

2. Get `API_SP_ID` for `apim-api-app`:

```bash
API_SP_ID=$(az ad sp list \
  --filter "displayName eq 'apim-api-app'" \
  --query "[0].id" -o tsv)
echo $API_SP_ID
```

3. Perform the app role assignment:

```bash
az rest \
  --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$CALLER_OID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{\"principalId\":\"$CALLER_OID\",\"resourceId\":\"$API_SP_ID\",\"appRoleId\":\"$APP_ROLE_ID\"}"
```

### Call APIM from the notebook with a service principal

```python
%pip install msal requests
dbutils.library.restartPython()
```

```python
import json
import msal
import requests

TENANT_ID = "<tenant-id>"
ADB_CLIENT_APP_ID = "<adb-client-app-client-id>"
APIM_API_APP_ID = "<apim-api-app-client-id>"
CLIENT_SECRET = dbutils.secrets.get(
    scope="<scope-name>",
    key="<adb-client-app-client-secret-key>",
)

app = msal.ConfidentialClientApplication(
    client_id=ADB_CLIENT_APP_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    client_credential=CLIENT_SECRET,
)

result = app.acquire_token_for_client(
    scopes=[f"api://{APIM_API_APP_ID}/.default"],
)

if "access_token" not in result:
    raise RuntimeError(
        "Token acquisition failed: "
        f"{result.get('error')} - {result.get('error_description')}"
    )

response = requests.post(
    "https://{your-apim-name}.azure-api.net/foundry/chat/completions",
    headers={
        "Authorization": f"Bearer {result['access_token']}",
        "Content-Type": "application/json",
    },
    json={
        "model": "{model-name}",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What are the top 3 most popular colors?"},
        ],
    },
    timeout=15,
)

response.raise_for_status()
print(json.dumps(response.json(), indent=2))
```

## Validate the End-to-End Flow

For the OBO flow, validate the following sequence:

1. The notebook receives a valid user assertion from an upstream trusted client or token broker.
2. The notebook exchanges that assertion for an APIM access token by using `acquire_token_on_behalf_of`.
3. APIM accepts the delegated token and validates the `scp` claim.
4. APIM acquires a managed identity token for `https://cognitiveservices.azure.com/`.
5. APIM forwards the request to Azure AI Foundry.
6. The Foundry response returns through APIM to the notebook.

For app-only flows, the same backend steps apply after the caller obtains a token with managed identity or client credentials.

## Troubleshooting

- `401 Unauthorized` at APIM before the backend call: inspect the caller token and confirm the `aud`, `iss`, and either `scp` or `roles` claims match the APIM policy.
- `scp` missing from an OBO token: the notebook likely did not receive a delegated user assertion, or the OBO client app does not have the `user_impersonation` delegated permission.
- `roles` missing from an app-only token: the managed identity or service principal does not have the APIM API app role assignment.
- `AADSTS50013` or similar OBO exchange errors: the user assertion was issued for the wrong upstream application, expired, or the OBO client app is missing consent.
- `403` or backend authorization failures at Foundry: confirm the APIM managed identity has the required Azure AI or Cognitive Services data-plane access to the Foundry endpoint.
- APIM validates the wrong token: make sure `validate-jwt` runs before APIM overwrites the `Authorization` header for the backend call.
- Connection timeouts from Databricks: verify private endpoint approval, VNet routing, DNS resolution, and any APIM gateway network restrictions.