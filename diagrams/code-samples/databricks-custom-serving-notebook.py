import mlflow.deployments

client = mlflow.deployments.get_deploy_client("databricks")

client.create_endpoint(
  name="foundry-via-apim-chat",
  config={
    "served_entities": [
      {
        "name": "foundry-via-apim",
        "external_model": {
          "name": "agent-model",                        # logical name in Databricks
          "provider": "custom",
          "task": "llm/v1/chat",
          "custom_provider_config": {
            # Must be the full endpoint URL, e.g. APIM route to chat completions
            "custom_provider_url": "https://{your-apim-name}.azure-api.net/foundry/chat/completions",

            # Auth – choose ONE approach:
            # A) bearer token auth OR
            # B) api key auth
            #
            # If you keep APIM subscription key, you'd typically map it in APIM policies.
            # Use a secret reference from Databricks secrets:
            "bearer_token_auth": {
              "token": "{{secrets/apim/apim-key}}"
            }
          }
        }
      }
    ]
  }
)