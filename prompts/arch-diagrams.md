## Objective
- Create an architecture diagram in [draw.io](https://app.diagrams.net/) for the project to visually represent the system's structure and components.
## Specifications
### Infrastructure Components
- **Foundry Account** resource: 
- **Azure API Management** resource 
- **Azure Databricks** resource
- **VNet** For Azure API Management: **VNET-APIM**
    - **Subnet** for Azure API Management: **APIM-SUBNET**
    - **Subnet** for Private Endpoint connection: **PE-SUBNET**
- **VNet** For Azure Databricks: **VNET-DATABRICKS**
    - **Subnet** for Azure Databricks Control Plane: **DATABRICKS-PRIVATE-SUBNET**
    - **Subnet** for Azure Databricks Worker Nodes: **DATABRICKS-PUBLIC-SUBNET**
    - **Subnet** for Private Endpoint connection: **PE-SUBNET**
- **Microsoft Entra ID** for app registration and role assignment
### Network Connectivity
 - **Azure API Management** resource:
   - **Network Injection** into **VNET-APIM**
   - **Private Endpoint** connection to **VNET-DATABRICKS** in "PE-SUBNET"
 - **Azure Databricks** resource:
   - Provisioned into **DATABRICKS-PRIVATE-SUBNET** and **DATABRICKS-PUBLIC-SUBNET** in **VNET-DATABRICKS**
- **Foundry Account** resource:
  - **Private Endpoint** connection to **VNET-APIM** in "PE-SUBNET"
### Access Control
- **Foundry Account** resource:
    - **Role Assignment**: Assign **AI User Role** role to APIM Managed Identity.
- **Entra ID** resource:
    - **app registration** for Azure Databricks Managed Identity to enable authentication and authorization for APIM API access.
- **Azure Databricks** resource:
    - Using **app registration** for Azure Databricks Managed Identity to enable authentication and authorization for API access.
- **Azure API Management** resource:
    - Using **Inbound Policies** to:
      - to validate jwt token from Azure Databricks Managed Identity for API access.
      - to pass jwt token from APIM Managed Identity to Foundry Account.
### Diagram Creation
- Use **draw.io** to create the architecture diagram.
 Create separate Layers for:
  - **Infrastructure Components**: Representing the Foundry Account, Azure API Management, Azure Databricks, VNets, and Microsoft Entra ID.
  - **Network Connectivity**: Illustrating the connections between the components, including network injection and private endpoint connections.
  - **Access Control**: Highlighting the role assignments and app registrations for authentication and authorization.