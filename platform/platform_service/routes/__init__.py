"""The platform API's routes, one router per area; app.py includes them in this order."""
from platform_service.routes import (authz, catalogue, connections, engine, evidence, facade, helpers, ledger, llm,
                                     projects)

ROUTERS = tuple(area.router for area in (projects, authz, llm, connections, engine, evidence, catalogue, facade,
                                         helpers, ledger))
