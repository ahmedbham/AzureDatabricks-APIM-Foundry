## Goal
- To create a guide that helps users connect Databricks Mosaic to Foundry via APIM.
## Key Steps
1. Create Databricks secret scope and key store APIM Subscription Key. Use databricks cli
2. Create a custom serving notebook in Databricks that uses the APIM endpoint for Foundry chat completions (see code sample in `code-samples/databricks-custom-serving-notebook.py`).
3. Configure private connectivity to Azure resources (APIM) using Network Connectivity Configuration (NCC) and Managed Private Endpoints in Databricks. Follow the steps in the Databricks documentation for setting up NCC and private endpoints here: https://learn.microsoft.com/en-us/azure/databricks/security/network/serverless-network-security/serverless-private-link
