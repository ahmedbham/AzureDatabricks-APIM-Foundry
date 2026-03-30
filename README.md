# Azure Databricks to Foundry via APIM

This repository documents two APIM-fronted integration patterns for Azure Databricks and Azure AI Foundry.

## Documents

- [azure-databricks-apim-foundry-setup.md](azure-databricks-apim-foundry-setup.md): Workspace flow that uses Azure Databricks managed identity or a service principal to call APIM, while APIM uses its managed identity for the Foundry backend hop.
- [databricks-mosaic-to-foundry-via-apim.md](databricks-mosaic-to-foundry-via-apim.md): Mosaic AI custom serving flow that sends an APIM subscription key from a Databricks secret and lets APIM use managed identity only on the backend hop.

## Architecture Assets

- [diagrams/adb-apim-foundry-architecture.drawio](diagrams/adb-apim-foundry-architecture.drawio): Editable architecture diagram.
- [diagrams/adb-apim-foundry-architecture.svg](diagrams/adb-apim-foundry-architecture.svg): Exported diagram preview.
- [diagrams/code-samples](diagrams/code-samples): APIM policy and Databricks notebook samples used by the guides.

Open the draw.io file in [draw.io](https://app.diagrams.net/) or the draw.io VS Code extension. The diagram includes layers for infrastructure, network connectivity, and access control.
