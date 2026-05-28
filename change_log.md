**0.1.7**
FIX: Support polymorphic (multi-table) lookup fields via `@odata.bind` navigation properties.
Fields like `customerid_account@odata.bind` on the Incident entity are now validated against
both regular entity attributes and single-valued navigation properties (ManyToOneRelationships).

**0.1.1**
Fixed public links in documentation.
MINOR: Tweaks to configuration schema to open links in new tab.

**0.1.0**
Documentation added.
Tweaked configuration schema.
Added sample configuration with examples.
FIX: Fixed error message when no ID was provided on delete operation.
FIX: Fixed default value for `continue_on_error` parameter, defaults to `true`.

**0.0.1**
Working version of the extractor which allows to query any entity supported by Microsoft Dynamics 365's Web API.
Automatic parsing and querying of the entities.