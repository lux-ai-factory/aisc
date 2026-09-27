--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: qualification; Type: SCHEMA; Schema: -; Owner: -
--



--
-- Name: SCHEMA qualification; Type: COMMENT; Schema: -; Owner: -
--



--
-- Name: answer_only_latest_changes(); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.answer_only_latest_changes() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NOT qualification.card_is_latest(
       (SELECT q.system_id FROM qualification.qualification q WHERE q.id = NEW."qualificationId")) THEN
    RAISE EXCEPTION 'AI card % is of a version that is not the latest: it is kept as it was', NEW."qualificationId";
  END IF;
  RETURN NEW;
END $$;


--
-- Name: card_is_latest(uuid); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.card_is_latest(version_pid uuid) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM core.system s
     WHERE s.pid = version_pid
       AND s.number = (SELECT max(o.number) FROM core.system o WHERE o.project_id = s.project_id));
END $$;


--
-- Name: component_only_latest_changes(); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.component_only_latest_changes() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NOT qualification.card_is_latest(
       (SELECT q.system_id FROM qualification.qualification q WHERE q.id = NEW.qualification_id)) THEN
    RAISE EXCEPTION 'AI card % is of a version that is not the latest: it is kept as it was', NEW.qualification_id;
  END IF;
  RETURN NEW;
END $$;


--
-- Name: qualification_only_latest_changes(); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.qualification_only_latest_changes() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NOT qualification.card_is_latest(OLD.system_id) THEN
    RAISE EXCEPTION 'AI card % is of a version that is not the latest: it is kept as it was', OLD.id;
  END IF;
  RETURN NEW;
END $$;


SET default_tablespace = '';


--
-- Name: _prisma_migrations; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification._prisma_migrations (
    id character varying(36) NOT NULL,
    checksum character varying(64) NOT NULL,
    finished_at timestamp with time zone,
    migration_name character varying(255) NOT NULL,
    logs text,
    rolled_back_at timestamp with time zone,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    applied_steps_count integer DEFAULT 0 NOT NULL
);


--
-- Name: card_component; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.card_component (
    id text NOT NULL,
    qualification_id text NOT NULL,
    component_pid uuid NOT NULL,
    airo_property text NOT NULL,
    name text NOT NULL,
    component_type text NOT NULL,
    object_name text DEFAULT ''::text NOT NULL,
    linked_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT card_component_airo_property_check CHECK ((airo_property = ANY (ARRAY['hasModel'::text, 'hasTrainingData'::text, 'hasTestingData'::text, 'hasValidationData'::text, 'hasComponent'::text])))
);


--
-- Name: knowledge_graph; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.knowledge_graph (
    id text NOT NULL,
    "qualificationId" text NOT NULL,
    digest text NOT NULL,
    turtle text NOT NULL,
    jsonld text NOT NULL,
    stamp text[] DEFAULT ARRAY[]::text[],
    nodes integer NOT NULL,
    triples integer NOT NULL,
    built_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: qualification; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.qualification (
    id text NOT NULL,
    "systemName" text NOT NULL,
    "systemVersion" text NOT NULL,
    company text NOT NULL,
    description text NOT NULL,
    "targetUseCase" text NOT NULL,
    "targetUsers" text NOT NULL,
    created_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) with time zone NOT NULL,
    "systemCard" text,
    system_card_at timestamp(3) with time zone,
    "systemCardJson" jsonb,
    "systemCardPdfPath" text,
    "targetSystemTags" text[] DEFAULT ARRAY[]::text[],
    "sectorTags" text[] DEFAULT ARRAY[]::text[],
    "marketFormTags" text[] DEFAULT ARRAY[]::text[],
    "localityTags" text[] DEFAULT ARRAY[]::text[],
    "intendedDeployers" text,
    "ontologyExtracted" jsonb,
    "ontologyPatch" jsonb,
    ontology_at timestamp(3) with time zone,
    project_id uuid NOT NULL,
    system_id uuid NOT NULL
);


--
-- Name: qualification_answer; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.qualification_answer (
    id text NOT NULL,
    "qualificationId" text NOT NULL,
    "toolId" text NOT NULL,
    "questionId" text NOT NULL,
    answer text NOT NULL
);


--
-- Name: qualification_risk; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.qualification_risk (
    id text NOT NULL,
    "qualificationId" text NOT NULL,
    "position" integer NOT NULL,
    risk text NOT NULL,
    source text NOT NULL,
    vulnerability text,
    consequence text NOT NULL,
    affected text NOT NULL,
    "impactAreas" text[] DEFAULT ARRAY[]::text[],
    control text NOT NULL,
    "followUpControl" text
);


--
-- Name: knowledge_graph KnowledgeGraph_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.knowledge_graph
    ADD CONSTRAINT "KnowledgeGraph_pkey" PRIMARY KEY (id);


--
-- Name: qualification_answer QualificationAnswer_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification_answer
    ADD CONSTRAINT "QualificationAnswer_pkey" PRIMARY KEY (id);


--
-- Name: qualification_risk QualificationRisk_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification_risk
    ADD CONSTRAINT "QualificationRisk_pkey" PRIMARY KEY (id);


--
-- Name: qualification Qualification_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification
    ADD CONSTRAINT "Qualification_pkey" PRIMARY KEY (id);


--
-- Name: _prisma_migrations _prisma_migrations_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification._prisma_migrations
    ADD CONSTRAINT _prisma_migrations_pkey PRIMARY KEY (id);


--
-- Name: card_component card_component_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.card_component
    ADD CONSTRAINT card_component_pkey PRIMARY KEY (id);


--
-- Name: KnowledgeGraph_qualificationId_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX "KnowledgeGraph_qualificationId_key" ON qualification.knowledge_graph USING btree ("qualificationId");


--
-- Name: QualificationAnswer_qualificationId_questionId_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX "QualificationAnswer_qualificationId_questionId_key" ON qualification.qualification_answer USING btree ("qualificationId", "questionId");


--
-- Name: QualificationAnswer_qualificationId_toolId_idx; Type: INDEX; Schema: qualification; Owner: -
--

CREATE INDEX "QualificationAnswer_qualificationId_toolId_idx" ON qualification.qualification_answer USING btree ("qualificationId", "toolId");


--
-- Name: QualificationRisk_qualificationId_idx; Type: INDEX; Schema: qualification; Owner: -
--

CREATE INDEX "QualificationRisk_qualificationId_idx" ON qualification.qualification_risk USING btree ("qualificationId");


--
-- Name: Qualification_project_id_idx; Type: INDEX; Schema: qualification; Owner: -
--

CREATE INDEX "Qualification_project_id_idx" ON qualification.qualification USING btree (project_id);


--
-- Name: card_component_component_pid_idx; Type: INDEX; Schema: qualification; Owner: -
--

CREATE INDEX card_component_component_pid_idx ON qualification.card_component USING btree (component_pid);


--
-- Name: card_component_qualification_id_component_pid_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX card_component_qualification_id_component_pid_key ON qualification.card_component USING btree (qualification_id, component_pid);


--
-- Name: qualification_system_id_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX qualification_system_id_key ON qualification.qualification USING btree (system_id);


--
-- Name: card_component card_component_only_latest_changes; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER card_component_only_latest_changes BEFORE INSERT OR UPDATE ON qualification.card_component FOR EACH ROW EXECUTE FUNCTION qualification.component_only_latest_changes();


--
-- Name: qualification_answer qualification_answer_only_latest_changes; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER qualification_answer_only_latest_changes BEFORE INSERT OR UPDATE ON qualification.qualification_answer FOR EACH ROW EXECUTE FUNCTION qualification.answer_only_latest_changes();


--
-- Name: qualification qualification_only_latest_changes; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER qualification_only_latest_changes BEFORE UPDATE ON qualification.qualification FOR EACH ROW EXECUTE FUNCTION qualification.qualification_only_latest_changes();


--
-- Name: knowledge_graph KnowledgeGraph_qualificationId_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.knowledge_graph
    ADD CONSTRAINT "KnowledgeGraph_qualificationId_fkey" FOREIGN KEY ("qualificationId") REFERENCES qualification.qualification(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: qualification_answer QualificationAnswer_qualificationId_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification_answer
    ADD CONSTRAINT "QualificationAnswer_qualificationId_fkey" FOREIGN KEY ("qualificationId") REFERENCES qualification.qualification(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: qualification_risk QualificationRisk_qualificationId_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification_risk
    ADD CONSTRAINT "QualificationRisk_qualificationId_fkey" FOREIGN KEY ("qualificationId") REFERENCES qualification.qualification(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: qualification Qualification_project_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification
    ADD CONSTRAINT "Qualification_project_id_fkey" FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE CASCADE;


--
-- Name: card_component card_component_qualification_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.card_component
    ADD CONSTRAINT card_component_qualification_id_fkey FOREIGN KEY (qualification_id) REFERENCES qualification.qualification(id) ON DELETE CASCADE;


--
-- Name: qualification qualification_system_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification
    ADD CONSTRAINT qualification_system_id_fkey FOREIGN KEY (system_id) REFERENCES core.system(pid) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


