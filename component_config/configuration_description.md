### Input tables

For each run, at least one input table needs to be specified. The name of the input table names marks the endpoint, to which the data will be loaded. For example, data from table `contacts.csv` will be written to endpoint `contacts`, data from `leads.csv` will be written to endpoint `leads`, etc. 

#### Valid entities (endpoints)

If one of the tables defines an entity (endpoint), which is not part of the target Dynamics CRM instance, an error will be raised before writing begins.

For a list of default Microsoft defined entities, please visit [Web API EntityType Reference](https://docs.microsoft.com/en-us/dynamics365/customer-engagement/web-api/entitytypes). This list, however, does not include custom created entities and fields. For a complete list of entities, visit `[ORGANIZATION_URL]/api/data/[API_VERSION]/EntityDefinitions?%24select=EntitySetName`, where `ORGANIZATION_URL` is a unique URL of the Dynamics CRM instance for your organization, and `API_VERSION` is the API version specification, you'd like to use; e.g. `https://keboola.crm.dynamics.com/api/data/v9.1/EntityDefinitions?%24select=EntitySetName`. 
*Note: If the above request returns page error (i.e. HTTP ERROR 401), you need to be logged in first to access the resouce.*

#### Mandatory columns

Each operation requires a set of columns to be included with each table.

##### Delete operation

For `delete` operation, which deletes records from target entities, only column `id` is required, which contains unique identificators of records to be deleted. IDs of particular records can be found in the URL of said record in the UI version of Microsoft Dynamics 365 or using the accompanying extractor component for Dynamics 365.

![record_id](https://bitbucket.org/kds_consulting_team/kds-team.wr-microsoft-dynamics/src/master/docs/images/record_id.png)

##### Upsert operation

For operation `upsert`, columns `id` and `data` are required. `id`, as is the case in previous case, must contain unique identifier of records to be upserted. The field cannot be left empty, i.e. every row must have a valid ID, which will be accepted by the WebAPI. This way, the upsert operation allows users to specify their own ID for each record (more on that in *Parameters* section).

In `data` column, a valid JSON or Python Dictionary representation must be provided, which will be forwarded to the API.

##### Create and update operation

All tables for this operation must have the same fields as in `upsert` operation with one exception, the `id` can be left blank. All blank IDs will be automatically created by the API and automatically assigned an ID. **This operation is recommended to be used over upsert.**

### Parameters

#### Organization URL (`organization_url`)

The URL of Dynamics 365 instance, where all API calls will be made. The URL can be discovered using [Global Discovery Service](https://docs.microsoft.com/en-us/powerapps/developer/common-data-service/webapi/discover-url-organization-web-api) or from the URL of web instance:

![organization_url](https://bitbucket.org/kds_consulting_team/kds-team.wr-microsoft-dynamics/src/master/docs/images/organization_url.png)

#### API Version (`api_version`)

The API version of WebAPI which will be used to query the data. For a list of available APIs, please visit [API reference](https://docs.microsoft.com/en-us/dynamics365/customerengagement/on-premises/developer/webapi/web-api-versions).

#### Operation (`operation`)

The operation, which should be performed on the data in the CRM. Available options are:

- **delete**
    - configuration name: `delete`
    - description: The operation deletes all records from the target CRM instance, which match the IDs provided. The operation cannot be reversed and deletes the records forever.
- **create and update**
    - configuration name: `create_and_update`
    - description: The operation updates records, which have an ID specified in the input table and creates those, where ID is left blank. This operation is **preferred over upserting the data**, since IDs creation and all necessary relationships are handled automatically via the API.
- **upsert**
    - configuration name: `upsert`
    - description: All of the data is upserted into the API, i.e. all existing records are updated and non-existent records are created. For each non-existent record, an ID **must** be provided, which matches the ID format used by CRM instance. Non-comfortable IDs will be rejected by the API.

#### Continue on Error (`continue_on_error`)

A boolean flag, which marks, whether the writer should continue, when an exception, either from the API or configuration table, is encountered. An exception can be any 4xx response from the API, i.e. error when creating/updating/deleting a record, or an invalid JSON, missing ID, etc.

If set to `true`, writer continues executing until all rows from input tables are processed. After the component is finished, **an output table** with all operations is created, where success or failure of each operation is recorded. If set to `false`, the application raises an exception immediately after encountering any error.