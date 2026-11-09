"""The platform API's routes, one router per area; app.py includes them in this order."""
from platform_service.routes import (authz, catalogue, connections, connectivity, engine, evidence, facade, helpers,
                                     ledger, llm, projects, proof_files)

ROUTERS = tuple(area.router for area in (projects, authz, llm, connections, connectivity, engine, evidence, catalogue,
                                         facade, helpers, ledger, proof_files))
