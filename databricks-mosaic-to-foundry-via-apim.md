# Connect Databricks Mosaic to Foundry via APIM

This guide shows how to expose an Azure AI Foundry chat model to Databricks Mosaic AI through Azure API Management (APIM). The pattern in this document is the custom serving pattern from [diagrams/code-samples/databricks-custom-serving-notebook.py](diagrams/code-samples/databricks-custom-serving-notebook.py):

1. Databricks Mosaic AI calls an APIM endpoint.
2. Databricks sends an APIM subscription key stored in a Databricks secret scope.
3. APIM authenticates to Azure AI Foundry by using its managed identity.
4. Azure AI Foundry returns the model response through APIM back to Databricks.

This document is intentionally separate from the workspace managed identity flow in [README.md](README.md). For the Mosaic custom serving path, keep APIM subscription-key protection on the public or private gateway and use managed identity only on the APIM-to-Foundry backend hop.

## Target Architecture

- Azure Databricks Mosaic AI Model Serving hosts a custom external model endpoint.
- Azure API Management fronts the Azure AI Foundry chat completions API.
- Azure AI Foundry hosts the target model deployment.
- Databricks Network Connectivity Configuration (NCC) and managed private endpoints provide private access from Databricks serverless compute to APIM.

## Prerequisites

- An Azure Databricks workspace with Mosaic AI Model Serving enabled.
- An Azure AI Foundry project or endpoint with a deployed chat-capable model.
- An APIM instance that can reach Azure AI Foundry.
- APIM managed identity enabled.
- Permission to create Databricks secret scopes and serving endpoints.
- Azure Databricks account admin access for NCC configuration.
- Databricks CLI 0.205 or later.

## Step 1: Prepare the Foundry Backend in APIM

### 1. Create or identify the Foundry chat endpoint

Deploy the model in Azure AI Foundry and note the chat completions route that APIM should front. If you imported the Foundry API into APIM by using the OpenAI v1 compatibility option, make sure the APIM route points to the chat completions operation you intend to expose.

### 2. Create APIM with managed identity enabled

Use an APIM tier that supports the networking pattern you need. For private access scenarios in this repo, Premium v2 is the expected choice.

Grant the APIM managed identity the role required to call the Foundry backend. In this repo, the intended role is the AI user role shown in the architecture notes.

### 3. Import the Foundry API into APIM

When importing the Foundry API into APIM:

- Use the OpenAI v1 compatibility option.
- Remove any extra `/openai/v1` fragment from the APIM API URL suffix if the import added it.
- Keep APIM subscription-key enforcement enabled for this Mosaic flow.

The last point matters because the Databricks custom serving sample stores an APIM subscription key in a Databricks secret. That is the client credential for the Databricks-to-APIM hop.

### 4. Add an APIM inbound policy for the two-hop auth flow

The Databricks custom serving sample passes a secret by using `bearer_token_auth`. For this pattern, APIM rewrites the incoming bearer value into `Ocp-Apim-Subscription-Key`, then obtains a managed identity token for the Foundry backend.

Example APIM policy:

```xml
<policies>
		<inbound>
				<base />

				<set-variable name="incoming-auth"
						value="@(context.Request.Headers.GetValueOrDefault(&quot;Authorization&quot;, &quot;&quot;))" />

				<choose>
						<when condition="@(!string.IsNullOrEmpty((string)context.Variables[&quot;incoming-auth&quot;]) && ((string)context.Variables[&quot;incoming-auth&quot;]).StartsWith(&quot;Bearer &quot;))">
								<set-header name="Ocp-Apim-Subscription-Key" exists-action="override">
										<value>@(((string)context.Variables["incoming-auth"]).Substring(7).Trim())</value>
								</set-header>
						</when>
						<otherwise>
								<return-response>
										<set-status code="401" reason="Missing bearer token" />
										<set-body>Authorization header with bearer token is required.</set-body>
								</return-response>
						</otherwise>
				</choose>

				<authentication-managed-identity
						resource="https://cognitiveservices.azure.com/"
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

- If you use a different APIM auth scheme for callers, adjust the first half of the policy accordingly.
- If your APIM API already requires a subscription key in the native `Ocp-Apim-Subscription-Key` header, this rewrite keeps the Databricks sample usable without changing the serving endpoint definition.
- If you want Databricks to send a dedicated header instead of a bearer token, update both the Databricks external model config and this policy together.

## Step 2: Create a Databricks Secret Scope for the APIM Subscription Key

Use the Databricks CLI to store the APIM subscription key that Mosaic AI will present to APIM.

### 1. Authenticate to the Databricks workspace

```bash
databricks auth login --host https://<your-databricks-workspace-url>
```

### 2. Create a secret scope

```bash
databricks secrets create-scope apim
```

### 3. Store the APIM subscription key

```bash
databricks secrets put-secret apim apim-key --string-value "<your-apim-subscription-key>"
```

### 4. Confirm the scope exists

```bash
databricks secrets list-scopes
databricks secrets list-secrets apim
```

At this point, Databricks can reference the secret as `{{secrets/apim/apim-key}}`.

## Step 3: Create the Databricks Mosaic Custom Serving Endpoint

Create a Mosaic AI serving endpoint that proxies chat completions through APIM.

The repo sample is in [diagrams/code-samples/databricks-custom-serving-notebook.py](diagrams/code-samples/databricks-custom-serving-notebook.py). The core configuration is:

```python
import mlflow.deployments

client = mlflow.deployments.get_deploy_client("databricks")

client.create_endpoint(
	name="foundry-via-apim-chat",
	config={
		"served_entities": [
			{
				"name": "foundry-via-apim",
				"external_model": {
					"name": "agent-model",
					"provider": "custom",
					"task": "llm/v1/chat",
					"custom_provider_config": {
						"custom_provider_url": "https://{your-apim-name}.azure-api.net/foundry/chat/completions",
						"bearer_token_auth": {
							"token": "{{secrets/apim/apim-key}}"
						}
					}
				}
			}
		]
	}
)
```

Replace the following values before running the notebook:

- `foundry-via-apim-chat`: the Databricks serving endpoint name.
- `agent-model`: the logical model name shown in Databricks.
- `https://{your-apim-name}.azure-api.net/foundry/chat/completions`: the APIM route that fronts your Foundry chat completions API.

Operational guidance:

- Keep the APIM route stable so the Databricks endpoint does not need to change when you rotate the backend model deployment.
- Rotate the APIM subscription key in APIM and then update the Databricks secret value with `databricks secrets put-secret`.
- Do not hardcode the subscription key in notebooks or serving configs.

## Step 4: Configure Private Connectivity from Databricks to APIM

For serverless Mosaic workloads, use Databricks Network Connectivity Configuration (NCC) and managed private endpoints so Databricks can reach a private APIM endpoint.

Reference: https://learn.microsoft.com/en-us/azure/databricks/security/network/serverless-network-security/serverless-private-link

### 1. Validate the NCC prerequisites

- The Databricks account and workspace must be on the Premium plan.
- The user performing the setup must be an Azure Databricks account admin.
- The NCC region must match the workspace region.

### 2. Create an NCC

In the Databricks account console:

1. Go to Security.
2. Open Network connectivity configurations.
3. Create a new NCC in the same region as the Databricks workspace.

Databricks recommends sharing an NCC across workspaces only when they have the same connectivity requirements.

### 3. Attach the NCC to the workspace

In the Databricks account console:

1. Open Workspaces.
2. Select the target workspace.
3. Update the workspace and assign the NCC.
4. Wait for the configuration to propagate.
5. Restart any running serverless services after the update.

### 4. Create a managed private endpoint rule for APIM

In the NCC:

1. Add a private endpoint rule.
2. Paste the Azure resource ID of the APIM instance.
3. Enter `Gateway` for Azure Subresource ID.
4. Save the rule and wait for the status to become `PENDING`.

Then in Azure:

1. Open the APIM resource.
2. Go to Networking.
3. Review Private endpoint connections.
4. Approve the pending Databricks private endpoint request.
5. Return to Databricks and confirm the rule status becomes `ESTABLISHED`.

If you also expose the Foundry backend privately to APIM, keep that private endpoint on the APIM side. The Databricks NCC in this pattern only needs private connectivity to APIM, not direct connectivity to Foundry.

### 5. Lock down public network access when validation is complete

After the private path is working end to end, disable public network access on the APIM entry point if that matches your security posture and DNS design.

Before disabling public access, verify that:

- The APIM private endpoint is approved.
- DNS for the APIM gateway hostname resolves to the private endpoint path used by your environment.
- Databricks serverless compute can still reach the APIM hostname through the NCC-attached workspace.

## Step 5: Validate the End-to-End Flow

Run the notebook that creates the Databricks Mosaic serving endpoint, then test the endpoint from Databricks Mosaic AI or from an application that calls the Databricks serving endpoint.

Expected flow:

1. The client calls the Databricks serving endpoint.
2. Databricks forwards the request to APIM and sends the secret-backed credential.
3. APIM validates or accepts the client-side credential and rewrites it as an APIM subscription key.
4. APIM acquires a managed identity token for `https://cognitiveservices.azure.com/`.
5. APIM forwards the request to Azure AI Foundry.
6. The model response returns back through APIM to Databricks.

## Troubleshooting

### 401 from APIM

- The Databricks secret does not contain the correct APIM subscription key.
- The APIM inbound policy is not rewriting the bearer token into `Ocp-Apim-Subscription-Key`.
- APIM subscription-key enforcement was disabled even though this flow expects it.

### 403 or 500 from Foundry through APIM

- APIM managed identity is missing the role needed on the Azure AI Foundry resource.
- The APIM backend configuration points to the wrong Foundry endpoint.
- The backend `Authorization` header is not being overwritten with the managed identity token.

### Timeout or name resolution errors from Databricks serverless

- The NCC is not attached to the workspace.
- The APIM private endpoint connection is still pending approval.
- Serverless workloads were not restarted after attaching the NCC.
- Public access was disabled before the private path and DNS resolution were verified.

### 404 or incorrect route behavior

- The APIM URL suffix still includes an extra `/openai/v1` segment.
- The Databricks `custom_provider_url` does not match the APIM operation route.

## References

- [README.md](README.md)
- [diagrams/code-samples/databricks-custom-serving-notebook.py](diagrams/code-samples/databricks-custom-serving-notebook.py)
- [diagrams/code-samples/apim-policy.xml](diagrams/code-samples/apim-policy.xml)
- Databricks NCC private connectivity: https://learn.microsoft.com/en-us/azure/databricks/security/network/serverless-network-security/serverless-private-link
- Databricks CLI secrets commands: https://learn.microsoft.com/en-us/azure/databricks/dev-tools/cli/reference/secrets-commands
