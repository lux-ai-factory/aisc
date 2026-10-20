"""The platform API's routes, one router per area; app.py includes them in this order."""
from platform_service.routes import authz, catalogue, connections, evidence, facade, ledger, llm, projects

ROUTERS = tuple(area.router for area in (projects, authz, llm, connections, evidence, catalogue, facade, ledger))
