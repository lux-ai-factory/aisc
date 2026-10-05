-- One beacon per witnessed request (page.* is per_request=1 in the registry).
CREATE UNIQUE INDEX IF NOT EXISTS page_view_one_per_request ON ledger.page_view (request_id)
    WHERE request_id IS NOT NULL;
