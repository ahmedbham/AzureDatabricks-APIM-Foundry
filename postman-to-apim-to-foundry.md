# Postman to APIM to Foundry

This guide documents a practical interactive test pattern for calling Azure AI Foundry through Azure API Management (APIM) from Postman:

1. The user signs in with Microsoft Entra ID inside Postman by using OAuth 2.0 Authorization Code with PKCE.
2. Postman sends the resulting delegated access token to the APIM endpoint.
3. APIM validates the incoming delegated token.
4. APIM acquires its own managed identity token for Azure AI Foundry.
5. APIM forwards the request to Foundry.

This pattern keeps the user-facing hop and the backend hop separate:

- Caller to APIM: delegated user token for the APIM-protected API.
- APIM to Foundry: APIM managed identity token for `https://cognitiveservices.azure.com/`.

## Important Constraint

This document supports interactive sign-in inside Postman only. The supported client-side flow is OAuth 2.0 Authorization Code with PKCE.

The reason is straightforward:

1. Postman natively supports Authorization Code with PKCE.
2. Entra ID issues a delegated access token for the APIM API scope.
3. APIM validates that caller token and uses managed identity only for the backend hop to Foundry.

This keeps the authentication model clean:

- User authentication happens once in Postman.
- APIM does not pass the user token to Foundry.
- Foundry sees only the APIM managed identity token.

## Target Architecture

- Postman sends a bearer token issued by Entra ID for the APIM API application.
- APIM validates the bearer token and required delegated scope.
- APIM uses its system-assigned or user-assigned managed identity to obtain a backend token for Foundry.
- Foundry receives only the APIM managed identity token, not the original caller token.

## Prerequisites

- An APIM instance with managed identity enabled.
- An Azure AI Foundry project or endpoint with a deployed model.
- Permission to create or update Microsoft Entra app registrations.
- Permission to assign Azure RBAC roles on the Foundry resource.
- Postman desktop or web client.
- PowerShell 7 or Windows PowerShell for the manual device-flow steps in this document.

## Step 1: Create the APIM API App Registration

Create an Entra app registration that represents the API surface published through APIM.

1. Open `Microsoft Entra ID -> App registrations -> New registration`.
2. Create an app such as `apim-api-app`.
3. Record these values:
   - `TENANT_ID`: the directory tenant ID.
   - `APIM_API_APP_ID`: the application client ID.
4. Open `Expose an API`.
5. Set the Application ID URI to `api://{APIM_API_APP_ID}`.
6. Add a delegated scope named `user_impersonation`.
7. Save the scope settings.

This app registration is the audience for the token that the user presents to APIM.

## Step 2: Create the Public Client App for Postman Interactive Sign-In

Create a second Entra app registration that acts as the public client used by Postman for interactive sign-in.

1. Create a new app registration such as `postman-interactive-client`.
2. Under `Authentication`, add the redirect URI `https://oauth.pstmn.io/v1/callback`.
3. Under `Authentication`, set `Allow public client flows` to `Yes`.
4. Open `API permissions`.
5. Add a permission to your `apim-api-app` registration.
6. Choose `Delegated permissions`.
7. Select `user_impersonation`.
8. Grant admin consent if your tenant requires it.
9. Record the client ID as `PUBLIC_CLIENT_APP_ID`.

This client does not need a client secret because PKCE is designed for public clients.

## Step 3: Grant APIM Access to Azure AI Foundry

Enable the APIM managed identity and grant it the data-plane role needed to invoke your Foundry endpoint.

1. Open the APIM resource.
2. Under `Identity`, enable the system-assigned managed identity if it is not already enabled.
3. Copy the managed identity principal ID.
4. Open the Azure AI Foundry or Azure AI Services resource that backs your endpoint.
5. Add the RBAC role required for inference to the APIM managed identity.

The exact role name depends on how your Foundry endpoint is backed. In many cases this is an Azure AI or Cognitive Services user role that permits inference calls.

## Step 4: Configure APIM to Validate the Caller Token and Use Managed Identity for Foundry

Use an inbound APIM policy that validates the caller token first, then acquires a backend token by using APIM managed identity.

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

Operational notes:

- Keep `validate-jwt` before `authentication-managed-identity`.
- APIM must validate the original caller token before it overwrites the `Authorization` header for the backend hop.
- The token audience must match the APIM API app registration.
- The token scope must include `user_impersonation`.

## Step 5: Configure OAuth 2.0 in Postman

Create the request in Postman and let Postman handle the interactive browser sign-in.

1. Create a new `POST` request.
2. Set the URL to your APIM operation, for example:

```text
https://<your-apim-name>.azure-api.net/foundry/chat/completions
```

3. Open the `Authorization` tab.
4. Choose `OAuth 2.0`.
5. Under `Configure New Token`, use these values:

```text
Token Name: apim-user-token
Grant Type: Authorization Code (With PKCE)
Callback URL: https://oauth.pstmn.io/v1/callback
Auth URL: https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize
Access Token URL: https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token
Client ID: <public-client-app-id>
Client Secret: <leave empty>
Scope: api://<apim-api-app-client-id>/user_impersonation offline_access openid profile
Code Challenge Method: S256
State: <optional-random-value>
Client Authentication: Send client credentials in body
```

6. Turn on `Authorize using browser` if you are using the Postman desktop app.
7. Select `Get New Access Token`.
8. Sign in with the target Entra user account and complete MFA if required.
9. Review the returned token details.
10. Select `Use Token`.
11. Open the `Headers` tab and confirm `Authorization: Bearer <token>` is present.
12. Set `Content-Type` to `application/json`.
13. Add a request body such as:

```json
{
  "model": "<model-name>",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "What are the top 3 most popular colors?"
    }
  ]
}
```

14. Send the request.

Expected behavior:

1. Postman opens the browser-based sign-in experience.
2. Entra authenticates the user and redirects back to Postman.
3. Postman exchanges the authorization code for an access token by using PKCE.
4. Postman sends that access token to APIM.

## Step 6: Expected End-to-End Flow

Expected flow:

1. Postman sends the user token to APIM.
2. APIM validates the token and delegated scope.
3. APIM replaces the `Authorization` header with its own managed identity token.
4. APIM forwards the request to Foundry.
5. Foundry returns the response through APIM back to Postman.

## Step 7: Validate the Token if the Call Fails

If APIM returns `401` or `403`, decode the token and verify:

1. `aud` matches the APIM API app registration.
2. `scp` contains `user_impersonation`.
3. `iss` matches your tenant.
4. `exp` is still valid.

Common causes of failure:

- The token was issued for the wrong audience, such as Microsoft Graph.
- The delegated scope was not granted or not consented.
- The Postman client redirect URI does not exactly match `https://oauth.pstmn.io/v1/callback`.
- The public client setting is disabled on the Postman client app registration.
- APIM validates the wrong audience value.
- APIM managed identity does not have permission to call Foundry.
- The APIM inbound policy overwrote `Authorization` before validating the caller token.

## Postman Collection Guidance

For repeatable testing, save the request in a collection and configure OAuth 2.0 at the collection level if multiple operations use the same APIM token. Postman can reuse the token until it expires, and can refresh it when the authorization server returns a refresh token.

## References

- Microsoft Entra authorization code flow: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
- Postman OAuth 2.0 documentation: https://learning.postman.com/docs/sending-requests/authorization/oauth-20/