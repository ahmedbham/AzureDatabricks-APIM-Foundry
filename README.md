# Azure Databricks to Foundry via APIM

This repository documents two APIM-fronted integration patterns for Azure Databricks and Azure AI Foundry.

## Documents

- [azure-databricks-apim-foundry-setup.md](azure-databricks-apim-foundry-setup.md): Primary setup guide for the Entra-protected APIM pattern. It now documents the interactive Databricks notebook On-Behalf-Of (OBO) flow first, then the app-only managed identity and service principal alternatives, while APIM uses its managed identity for the Foundry backend hop.
- [databricks-mosaic-to-foundry-via-apim.md](databricks-mosaic-to-foundry-via-apim.md): Mosaic AI custom serving flow that sends an APIM subscription key from a Databricks secret and lets APIM use managed identity only on the backend hop.

## Architecture Assets

- [diagrams/adb-apim-foundry-architecture.drawio](diagrams/adb-apim-foundry-architecture.drawio): Editable architecture diagram.
- [diagrams/adb-apim-foundry-architecture.svg](diagrams/adb-apim-foundry-architecture.svg): Exported diagram preview.
- [diagrams/code-samples](diagrams/code-samples): APIM policy plus Databricks notebook samples for OBO, managed identity, and Mosaic custom serving flows.

## Recommended Reading Order

1. Start with [azure-databricks-apim-foundry-setup.md](azure-databricks-apim-foundry-setup.md) if you want Entra ID authentication from Databricks to APIM.
2. Use the OBO section in that guide only when the notebook truly acts on behalf of an interactive user and receives a valid upstream user assertion.
3. Use the managed identity or service principal sections in that guide for unattended jobs and service-to-service access.
4. Use [databricks-mosaic-to-foundry-via-apim.md](databricks-mosaic-to-foundry-via-apim.md) only for the Mosaic custom serving pattern that relies on an APIM subscription key.

Open the draw.io file in [draw.io](https://app.diagrams.net/) or the draw.io VS Code extension. The diagram includes layers for infrastructure, network connectivity, and access control.
