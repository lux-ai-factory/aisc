-- The chart assistant is an agent with a model choice of its own (Manage > Connectivity), as the card agent and the
-- risk mapper are.
ALTER TABLE connection.use DROP CONSTRAINT IF EXISTS use_agent_check;
ALTER TABLE connection.use ADD CONSTRAINT use_agent_check
    CHECK (agent IN ('card_agent', 'risk_mapper', 'chart_assistant'));
