"""The platform API's routes, one router per area; app.py includes them in this order."""
from platform_service.routes import (allowed_hosts, authz, catalogue, connections, connectivity, engine, evidence,
                                     facade, helpers, ledger, llm, projects, proof_files, run_passes, targets,
                                     work)

ROUTERS = tuple(area.router for area in (projects, authz, llm, connections, run_passes, targets, allowed_hosts,
                                         connectivity, engine, evidence, catalogue, facade, helpers, ledger,
                                         proof_files, work))
