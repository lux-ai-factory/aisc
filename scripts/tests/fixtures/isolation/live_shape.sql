-- Schema-only shape of the moving schemas of the live platform database, taken 2026-09-25 from the
-- restored rehearsal copy (live-20260925-1149.sql) in a throwaway container. No data, no owners, no ACLs.
-- Used by the catalog-diff tests of I3.7 and I7.9 (isolation 02-tests.md).
--
-- PostgreSQL database dump
--


-- Dumped from database version 14.21
-- Dumped by pg_dump version 14.21

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: project; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.project (
    pid uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE project; Type: COMMENT; Schema: core; Owner: -
--

COMMENT ON TABLE core.project IS 'An assessment, defined once for the whole platform.';


--
-- Name: project_member; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.project_member (
    project_id uuid NOT NULL,
    subject text NOT NULL,
    email text,
    role text NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT project_member_role_check CHECK ((role = ANY (ARRAY['viewer'::text, 'editor'::text, 'owner'::text])))
);


--
-- Name: TABLE project_member; Type: COMMENT; Schema: core; Owner: -
--

COMMENT ON TABLE core.project_member IS 'Who is in a project, and as what: viewer reads, editor changes the work, owner also decides who is in.';


--
-- Name: schema_migration; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.schema_migration (
    name text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: system; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.system (
    pid uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    name text NOT NULL,
    version text,
    provider text,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    number integer NOT NULL,
    created_by text,
    CONSTRAINT system_number_positive CHECK ((number > 0))
);


--
-- Name: TABLE system; Type: COMMENT; Schema: core; Owner: -
--

COMMENT ON TABLE core.system IS 'One saved AI card version of the project''s one AI system; number 1, 2, ... per project.';


--
-- Name: project_member project_member_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.project_member
    ADD CONSTRAINT project_member_pkey PRIMARY KEY (project_id, subject);


--
-- Name: project project_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.project
    ADD CONSTRAINT project_pkey PRIMARY KEY (pid);


--
-- Name: project project_slug_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.project
    ADD CONSTRAINT project_slug_key UNIQUE (slug);


--
-- Name: schema_migration schema_migration_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.schema_migration
    ADD CONSTRAINT schema_migration_pkey PRIMARY KEY (name);


--
-- Name: system system_pid_project_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.system
    ADD CONSTRAINT system_pid_project_id_key UNIQUE (pid, project_id);


--
-- Name: system system_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.system
    ADD CONSTRAINT system_pkey PRIMARY KEY (pid);


--
-- Name: system system_project_number_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.system
    ADD CONSTRAINT system_project_number_key UNIQUE (project_id, number);


--
-- Name: project_created_at_idx; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX project_created_at_idx ON core.project USING btree (created_at DESC);


--
-- Name: project_member_subject_idx; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX project_member_subject_idx ON core.project_member USING btree (subject);


--
-- Name: system_project_idx; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX system_project_idx ON core.system USING btree (project_id);


--
-- Name: system system_only_latest_changes; Type: TRIGGER; Schema: core; Owner: -
--

CREATE TRIGGER system_only_latest_changes BEFORE UPDATE ON core.system FOR EACH ROW EXECUTE FUNCTION core.system_only_latest_changes();


--
-- Name: project_member project_member_project_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.project_member
    ADD CONSTRAINT project_member_project_id_fkey FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE CASCADE;


--
-- Name: system system_project_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.system
    ADD CONSTRAINT system_project_id_fkey FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


--
-- PostgreSQL database dump
--


-- Dumped from database version 14.21
-- Dumped by pg_dump version 14.21

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: control_objectives; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA control_objectives;


--
-- Name: SCHEMA control_objectives; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA control_objectives IS 'Step 2: risks, mappings and their runs.';


--
-- Name: engine; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA engine;


--
-- Name: SCHEMA engine; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA engine IS 'standard public schema';


--
-- Name: qualification; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA qualification;


--
-- Name: SCHEMA qualification; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA qualification IS 'Step 1: qualifications and system cards.';


--
-- Name: report_composer; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA report_composer;


--
-- Name: SCHEMA report_composer; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA report_composer IS 'Step 7: report layouts, templates and generated reports.';


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
-- Name: form_builtin_is_fixed(); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.form_builtin_is_fixed() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM qualification.form f WHERE f.id = NEW.form_id AND f.origin = 'builtin')
     AND EXISTS (SELECT 1 FROM qualification.form_version v WHERE v.form_id = NEW.form_id) THEN
    RAISE EXCEPTION 'form % is builtin: it has one version, made by a migration', NEW.form_id;
  END IF;
  RETURN NEW;
END $$;


--
-- Name: form_name_is_fixed(); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.form_name_is_fixed() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.name IS DISTINCT FROM OLD.name OR NEW.origin IS DISTINCT FROM OLD.origin
     OR NEW.listed IS DISTINCT FROM OLD.listed THEN
    RAISE EXCEPTION 'form % keeps its name, origin and listing: only its description changes', OLD.id;
  END IF;
  RETURN NEW;
END $$;


--
-- Name: form_question_identity_is_fixed(); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.form_question_identity_is_fixed() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'form question % cannot be deleted: versions refer to it', OLD.id;
  END IF;
  IF NEW.scope IS DISTINCT FROM OLD.scope OR NEW.local_id IS DISTINCT FROM OLD.local_id
     OR NEW.owner_form_id IS DISTINCT FROM OLD.owner_form_id
     OR NEW.copied_from_id IS DISTINCT FROM OLD.copied_from_id THEN
    RAISE EXCEPTION 'form question % keeps its identity: scope, local id, owner and source are fixed', OLD.id;
  END IF;
  RETURN NEW;
END $$;


--
-- Name: form_version_is_append_only(); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.form_version_is_append_only() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION 'form version % is immutable: save a new version instead', OLD.id;
END $$;


--
-- Name: form_version_question_is_append_only(); Type: FUNCTION; Schema: qualification; Owner: -
--

CREATE FUNCTION qualification.form_version_question_is_append_only() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION 'form version % is immutable: save a new version instead', OLD.form_version_id;
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

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: control_objectives; Owner: -
--

CREATE TABLE control_objectives.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: graph; Type: TABLE; Schema: control_objectives; Owner: -
--

CREATE TABLE control_objectives.graph (
    project_id character varying(32) NOT NULL,
    jsonld text NOT NULL,
    digest character varying(64) NOT NULL,
    risks integer NOT NULL,
    uploaded_at timestamp with time zone NOT NULL
);


--
-- Name: mapped_objective; Type: TABLE; Schema: control_objectives; Owner: -
--

CREATE TABLE control_objectives.mapped_objective (
    id integer NOT NULL,
    risk_row_id integer NOT NULL,
    objective_id text NOT NULL,
    quote text NOT NULL,
    rationale text NOT NULL
);


--
-- Name: mapped_objective_id_seq; Type: SEQUENCE; Schema: control_objectives; Owner: -
--

CREATE SEQUENCE control_objectives.mapped_objective_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mapped_objective_id_seq; Type: SEQUENCE OWNED BY; Schema: control_objectives; Owner: -
--

ALTER SEQUENCE control_objectives.mapped_objective_id_seq OWNED BY control_objectives.mapped_objective.id;


--
-- Name: mapping_run; Type: TABLE; Schema: control_objectives; Owner: -
--

CREATE TABLE control_objectives.mapping_run (
    project_id character varying(32) NOT NULL,
    findings jsonb NOT NULL,
    stops jsonb NOT NULL,
    stop text NOT NULL,
    attempts integer NOT NULL,
    error text NOT NULL,
    model text NOT NULL,
    ran_at timestamp with time zone NOT NULL
);


--
-- Name: project; Type: TABLE; Schema: control_objectives; Owner: -
--

CREATE TABLE control_objectives.project (
    id character varying(32) NOT NULL,
    name text NOT NULL,
    objectives_digest character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    project_id uuid NOT NULL,
    system_id uuid NOT NULL
);


--
-- Name: risk; Type: TABLE; Schema: control_objectives; Owner: -
--

CREATE TABLE control_objectives.risk (
    id integer NOT NULL,
    project_id character varying(32) NOT NULL,
    risk_id text NOT NULL,
    "position" integer NOT NULL,
    text text NOT NULL,
    short_label text NOT NULL,
    source text NOT NULL,
    vulnerability text NOT NULL,
    consequence text NOT NULL,
    impact text NOT NULL,
    stakeholder text NOT NULL,
    control text NOT NULL,
    follow_up_control text NOT NULL,
    areas text[] NOT NULL,
    vair_terms text[] NOT NULL,
    provenance text NOT NULL,
    severity integer
);


--
-- Name: risk_id_seq; Type: SEQUENCE; Schema: control_objectives; Owner: -
--

CREATE SEQUENCE control_objectives.risk_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_id_seq; Type: SEQUENCE OWNED BY; Schema: control_objectives; Owner: -
--

ALTER SEQUENCE control_objectives.risk_id_seq OWNED BY control_objectives.risk.id;


--
-- Name: aisc_backend_aicomponent; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_aicomponent (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    data character varying(255) NOT NULL,
    file_size bigint,
    storage_container character varying(255) NOT NULL,
    component_type character varying(50) NOT NULL,
    json_value jsonb NOT NULL,
    source_dataset_id bigint,
    system_id bigint NOT NULL
);


--
-- Name: aisc_backend_aisystem; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_aisystem (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    project_id bigint NOT NULL
);


--
-- Name: aisc_backend_aicomponent_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_aicomponent ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_aicomponent_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_aisystem_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_aisystem ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_aisystem_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_artifact; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_artifact (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    data character varying(255) NOT NULL,
    storage_container character varying(255) NOT NULL,
    evaluation_plugin_id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    file_size bigint
);


--
-- Name: aisc_backend_artifact_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_artifact ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_artifact_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_evaluation; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_evaluation (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    status character varying(255) NOT NULL,
    task uuid,
    project_id bigint NOT NULL,
    system_id uuid,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: aisc_backend_evaluation_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_evaluation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_evaluation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_evaluationinput; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_evaluationinput (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    value jsonb NOT NULL,
    component_id bigint NOT NULL,
    evaluation_plugin_id bigint NOT NULL
);


--
-- Name: aisc_backend_evaluationinput_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_evaluationinput ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_evaluationinput_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_evaluationplugin; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_evaluationplugin (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    evaluation_id bigint NOT NULL,
    plugin_config_id bigint,
    error_message text NOT NULL,
    finished_at timestamp with time zone,
    started_at timestamp with time zone,
    status character varying(50) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: aisc_backend_evaluationplugin_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_evaluationplugin ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_evaluationplugin_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_measurement; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_measurement (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    unit character varying(255),
    "time" timestamp with time zone NOT NULL,
    score double precision NOT NULL,
    error character varying(255),
    uncertainty double precision NOT NULL,
    metric_id bigint NOT NULL,
    observation_id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    dimensions jsonb,
    direction character varying(50)
);


--
-- Name: aisc_backend_measurement_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_measurement ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_measurement_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_metric; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_metric (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    type_spec character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: aisc_backend_metric_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_metric ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_metric_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_metriccategory; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_metriccategory (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: aisc_backend_metriccategory_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_metriccategory ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_metriccategory_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_metriccategory_metrics; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_metriccategory_metrics (
    id bigint NOT NULL,
    metriccategory_id bigint NOT NULL,
    metric_id bigint NOT NULL
);


--
-- Name: aisc_backend_metriccategory_metrics_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_metriccategory_metrics ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_metriccategory_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_observation; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_observation (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    observer character varying(255) NOT NULL,
    tool character varying(255) NOT NULL,
    evaluation_id bigint NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: aisc_backend_observation_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_observation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_observation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_plugin; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_plugin (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    project_id bigint NOT NULL,
    current_config_id bigint,
    package_name character varying(255) NOT NULL,
    version character varying(50) NOT NULL,
    display_name character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    enabled boolean NOT NULL,
    catalogue_slug character varying(255)
);


--
-- Name: aisc_backend_plugin_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_plugin ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_plugin_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_pluginconfig; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_pluginconfig (
    id bigint NOT NULL,
    config jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    plugin_id bigint NOT NULL,
    description character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    pid uuid NOT NULL
);


--
-- Name: aisc_backend_pluginconfig_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_pluginconfig ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_pluginconfig_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_pluginconfigprojectconfig; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_pluginconfigprojectconfig (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    plugin_config_key character varying(255) NOT NULL,
    plugin_config_id bigint NOT NULL,
    project_config_id bigint NOT NULL
);


--
-- Name: aisc_backend_pluginconfigsetting_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_pluginconfigprojectconfig ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_pluginconfigsetting_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_project; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_project (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    status character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    project_id uuid
);


--
-- Name: aisc_backend_project_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_project ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_project_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_projectconfig; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_projectconfig (
    id bigint NOT NULL,
    pid uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    key character varying(255) NOT NULL,
    category character varying(50) NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    encrypted_value text NOT NULL,
    masked_value character varying(255) NOT NULL,
    json_value jsonb NOT NULL,
    project_id bigint NOT NULL
);


--
-- Name: aisc_backend_projectsetting_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.aisc_backend_projectconfig ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.aisc_backend_projectsetting_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: aisc_backend_derived; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_derived (
    metric_ptr_id bigint NOT NULL,
    expression character varying(255) NOT NULL,
    base_metric_id bigint NOT NULL
);


--
-- Name: aisc_backend_direct; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.aisc_backend_direct (
    metric_ptr_id bigint NOT NULL
);


--
-- Name: django_content_type; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: engine; Owner: -
--

CREATE TABLE engine.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: engine; Owner: -
--

ALTER TABLE engine.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME engine.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


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
-- Name: form; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.form (
    id text NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    origin text NOT NULL,
    listed boolean DEFAULT true NOT NULL,
    created_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT form_builtin_is_the_default CHECK (((origin <> 'builtin'::text) OR ((id = 'annex-iv-default'::text) AND listed))),
    CONSTRAINT form_name_length CHECK (((length(btrim(name)) >= 1) AND (length(btrim(name)) <= 120))),
    CONSTRAINT form_origin_check CHECK ((origin = ANY (ARRAY['builtin'::text, 'builder'::text, 'import'::text])))
);


--
-- Name: form_question; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.form_question (
    id text NOT NULL,
    owner_form_id text NOT NULL,
    scope text NOT NULL,
    local_id text NOT NULL,
    copied_from_id text,
    created_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT form_question_local_id_check CHECK ((local_id ~ '^[a-z0-9]+$'::text)),
    CONSTRAINT form_question_scope_check CHECK ((scope ~ '^[a-z0-9-]+$'::text))
);


--
-- Name: form_version; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.form_version (
    id text NOT NULL,
    form_id text NOT NULL,
    number integer NOT NULL,
    blocks text[] NOT NULL,
    created_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT form_version_blocks_check CHECK ((blocks <@ ARRAY['description'::text, 'targetUseCase'::text, 'targetUsers'::text, 'intendedDeployers'::text, 'targetSystemTags'::text, 'sectorTags'::text, 'marketFormTags'::text, 'localityTags'::text, 'risks'::text])),
    CONSTRAINT form_version_number_check CHECK ((number >= 1))
);


--
-- Name: form_version_question; Type: TABLE; Schema: qualification; Owner: -
--

CREATE TABLE qualification.form_version_question (
    form_version_id text NOT NULL,
    question_id text NOT NULL,
    "position" integer NOT NULL,
    text text NOT NULL,
    citation text DEFAULT ''::text NOT NULL,
    required boolean NOT NULL,
    annex_point text,
    group_label text,
    CONSTRAINT form_version_question_annex_point_check CHECK (((annex_point IS NULL) OR (annex_point = ANY (ARRAY['1a'::text, '1b'::text, '1c'::text, '1de'::text, '1f'::text, '1gh'::text, '2a'::text, '2b'::text, '2c'::text, '2d'::text, '2e'::text, '2f'::text, '2g'::text, '2h'::text])))),
    CONSTRAINT form_version_question_citation_check CHECK ((length(citation) <= 200)),
    CONSTRAINT form_version_question_position_check CHECK (("position" >= 0)),
    CONSTRAINT form_version_question_text_check CHECK (((length(btrim(text)) >= 1) AND (length(btrim(text)) <= 2000)))
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
    system_id uuid NOT NULL,
    form_version_id text
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
-- Name: generated_report; Type: TABLE; Schema: report_composer; Owner: -
--

CREATE TABLE report_composer.generated_report (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    layout_id uuid NOT NULL,
    layout_revision integer NOT NULL,
    project_id uuid NOT NULL,
    system_id uuid NOT NULL,
    snapshot jsonb NOT NULL,
    status text NOT NULL,
    pdf bytea,
    sha256 text,
    size_bytes integer,
    block_statuses jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_ref text,
    error_code text,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT generated_report_status_check CHECK ((status = ANY (ARRAY['running'::text, 'done'::text, 'partial'::text, 'failed'::text])))
);


--
-- Name: layout; Type: TABLE; Schema: report_composer; Owner: -
--

CREATE TABLE report_composer.layout (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    system_id uuid NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    revision integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by text NOT NULL,
    template_id uuid,
    CONSTRAINT layout_name_check CHECK (((char_length(name) >= 1) AND (char_length(name) <= 120))),
    CONSTRAINT layout_revision_check CHECK ((revision >= 1))
);


--
-- Name: layout_block; Type: TABLE; Schema: report_composer; Owner: -
--

CREATE TABLE report_composer.layout_block (
    layout_id uuid NOT NULL,
    instance_id uuid NOT NULL,
    "position" integer NOT NULL,
    block_type text NOT NULL,
    options jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT layout_block_position_check CHECK (("position" >= 0))
);


--
-- Name: schema_migration; Type: TABLE; Schema: report_composer; Owner: -
--

CREATE TABLE report_composer.schema_migration (
    name text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: template; Type: TABLE; Schema: report_composer; Owner: -
--

CREATE TABLE report_composer.template (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    name text NOT NULL,
    font text NOT NULL,
    font_size_pt numeric(4,1) NOT NULL,
    primary_color text NOT NULL,
    accent_color text NOT NULL,
    logo_mime text,
    logo bytea,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by text NOT NULL,
    CONSTRAINT template_accent_color_check CHECK ((accent_color ~ '^#[0-9a-fA-F]{6}$'::text)),
    CONSTRAINT template_check CHECK (((logo IS NULL) = (logo_mime IS NULL))),
    CONSTRAINT template_font_check CHECK ((font ~ '^[a-z0-9-]{1,40}$'::text)),
    CONSTRAINT template_font_size_pt_check CHECK (((font_size_pt >= (8)::numeric) AND (font_size_pt <= (16)::numeric))),
    CONSTRAINT template_logo_check CHECK ((octet_length(logo) <= 1048576)),
    CONSTRAINT template_logo_mime_check CHECK ((logo_mime = ANY (ARRAY['image/png'::text, 'image/jpeg'::text, 'image/svg+xml'::text]))),
    CONSTRAINT template_name_check CHECK (((char_length(name) >= 1) AND (char_length(name) <= 120))),
    CONSTRAINT template_primary_color_check CHECK ((primary_color ~ '^#[0-9a-fA-F]{6}$'::text))
);


--
-- Name: mapped_objective id; Type: DEFAULT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.mapped_objective ALTER COLUMN id SET DEFAULT nextval('control_objectives.mapped_objective_id_seq'::regclass);


--
-- Name: risk id; Type: DEFAULT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.risk ALTER COLUMN id SET DEFAULT nextval('control_objectives.risk_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: graph graph_pkey; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.graph
    ADD CONSTRAINT graph_pkey PRIMARY KEY (project_id);


--
-- Name: mapped_objective mapped_objective_pkey; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.mapped_objective
    ADD CONSTRAINT mapped_objective_pkey PRIMARY KEY (id);


--
-- Name: mapped_objective mapped_objective_risk_row_id_objective_id_key; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.mapped_objective
    ADD CONSTRAINT mapped_objective_risk_row_id_objective_id_key UNIQUE (risk_row_id, objective_id);


--
-- Name: mapping_run mapping_run_pkey; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.mapping_run
    ADD CONSTRAINT mapping_run_pkey PRIMARY KEY (project_id);


--
-- Name: project project_pkey; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.project
    ADD CONSTRAINT project_pkey PRIMARY KEY (id);


--
-- Name: risk risk_pkey; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.risk
    ADD CONSTRAINT risk_pkey PRIMARY KEY (id);


--
-- Name: risk risk_project_id_risk_id_key; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.risk
    ADD CONSTRAINT risk_project_id_risk_id_key UNIQUE (project_id, risk_id);


--
-- Name: project uq_project_system_id; Type: CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.project
    ADD CONSTRAINT uq_project_system_id UNIQUE (system_id);


--
-- Name: aisc_backend_aicomponent aisc_backend_aicomponent_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_aicomponent
    ADD CONSTRAINT aisc_backend_aicomponent_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_aisystem aisc_backend_aisystem_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_aisystem
    ADD CONSTRAINT aisc_backend_aisystem_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_aisystem aisc_backend_aisystem_project_id_key; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_aisystem
    ADD CONSTRAINT aisc_backend_aisystem_project_id_key UNIQUE (project_id);


--
-- Name: aisc_backend_artifact aisc_backend_artifact_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_artifact
    ADD CONSTRAINT aisc_backend_artifact_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_derived aisc_backend_derived_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_derived
    ADD CONSTRAINT aisc_backend_derived_pkey PRIMARY KEY (metric_ptr_id);


--
-- Name: aisc_backend_direct aisc_backend_direct_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_direct
    ADD CONSTRAINT aisc_backend_direct_pkey PRIMARY KEY (metric_ptr_id);


--
-- Name: aisc_backend_evaluation aisc_backend_evaluation_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluation
    ADD CONSTRAINT aisc_backend_evaluation_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_evaluationinput aisc_backend_evaluationi_evaluation_plugin_id_nam_5415cb96_uniq; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluationinput
    ADD CONSTRAINT aisc_backend_evaluationi_evaluation_plugin_id_nam_5415cb96_uniq UNIQUE (evaluation_plugin_id, name);


--
-- Name: aisc_backend_evaluationinput aisc_backend_evaluationinput_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluationinput
    ADD CONSTRAINT aisc_backend_evaluationinput_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_evaluationplugin aisc_backend_evaluationplugin_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluationplugin
    ADD CONSTRAINT aisc_backend_evaluationplugin_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_measurement aisc_backend_measurement_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_measurement
    ADD CONSTRAINT aisc_backend_measurement_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_metric aisc_backend_metric_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_metric
    ADD CONSTRAINT aisc_backend_metric_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_metriccategory_metrics aisc_backend_metriccateg_metriccategory_id_metric_1be78dc7_uniq; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_metriccategory_metrics
    ADD CONSTRAINT aisc_backend_metriccateg_metriccategory_id_metric_1be78dc7_uniq UNIQUE (metriccategory_id, metric_id);


--
-- Name: aisc_backend_metriccategory_metrics aisc_backend_metriccategory_metrics_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_metriccategory_metrics
    ADD CONSTRAINT aisc_backend_metriccategory_metrics_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_metriccategory aisc_backend_metriccategory_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_metriccategory
    ADD CONSTRAINT aisc_backend_metriccategory_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_observation aisc_backend_observation_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_observation
    ADD CONSTRAINT aisc_backend_observation_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_plugin aisc_backend_plugin_name_project_id_version__9895eff6_uniq; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_plugin
    ADD CONSTRAINT aisc_backend_plugin_name_project_id_version__9895eff6_uniq UNIQUE (name, project_id, version, package_name);


--
-- Name: aisc_backend_plugin aisc_backend_plugin_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_plugin
    ADD CONSTRAINT aisc_backend_plugin_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_pluginconfig aisc_backend_pluginconfig_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_pluginconfig
    ADD CONSTRAINT aisc_backend_pluginconfig_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_pluginconfigprojectconfig aisc_backend_pluginconfigsetting_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_pluginconfigprojectconfig
    ADD CONSTRAINT aisc_backend_pluginconfigsetting_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_project aisc_backend_project_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_project
    ADD CONSTRAINT aisc_backend_project_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_projectconfig aisc_backend_projectsetting_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_projectconfig
    ADD CONSTRAINT aisc_backend_projectsetting_pkey PRIMARY KEY (id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: aisc_backend_pluginconfigprojectconfig unique_plugin_config_project_config_key; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_pluginconfigprojectconfig
    ADD CONSTRAINT unique_plugin_config_project_config_key UNIQUE (plugin_config_id, plugin_config_key);


--
-- Name: aisc_backend_projectconfig unique_project_config_key; Type: CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_projectconfig
    ADD CONSTRAINT unique_project_config_key UNIQUE (project_id, category, key);


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
-- Name: form form_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form
    ADD CONSTRAINT form_pkey PRIMARY KEY (id);


--
-- Name: form_question form_question_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form_question
    ADD CONSTRAINT form_question_pkey PRIMARY KEY (id);


--
-- Name: form_version form_version_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form_version
    ADD CONSTRAINT form_version_pkey PRIMARY KEY (id);


--
-- Name: form_version_question form_version_question_pkey; Type: CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form_version_question
    ADD CONSTRAINT form_version_question_pkey PRIMARY KEY (form_version_id, question_id);


--
-- Name: generated_report generated_report_pkey; Type: CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.generated_report
    ADD CONSTRAINT generated_report_pkey PRIMARY KEY (id);


--
-- Name: layout_block layout_block_layout_id_position_key; Type: CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout_block
    ADD CONSTRAINT layout_block_layout_id_position_key UNIQUE (layout_id, "position");


--
-- Name: layout_block layout_block_pkey; Type: CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout_block
    ADD CONSTRAINT layout_block_pkey PRIMARY KEY (layout_id, instance_id);


--
-- Name: layout layout_pkey; Type: CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout
    ADD CONSTRAINT layout_pkey PRIMARY KEY (id);


--
-- Name: layout layout_project_id_name_key; Type: CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout
    ADD CONSTRAINT layout_project_id_name_key UNIQUE (project_id, name);


--
-- Name: schema_migration schema_migration_pkey; Type: CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.schema_migration
    ADD CONSTRAINT schema_migration_pkey PRIMARY KEY (name);


--
-- Name: template template_pkey; Type: CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.template
    ADD CONSTRAINT template_pkey PRIMARY KEY (id);


--
-- Name: template template_project_id_name_key; Type: CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.template
    ADD CONSTRAINT template_project_id_name_key UNIQUE (project_id, name);


--
-- Name: ix_mapped_objective_risk_row_id; Type: INDEX; Schema: control_objectives; Owner: -
--

CREATE INDEX ix_mapped_objective_risk_row_id ON control_objectives.mapped_objective USING btree (risk_row_id);


--
-- Name: ix_project_project_id; Type: INDEX; Schema: control_objectives; Owner: -
--

CREATE INDEX ix_project_project_id ON control_objectives.project USING btree (project_id);


--
-- Name: ix_risk_project_id; Type: INDEX; Schema: control_objectives; Owner: -
--

CREATE INDEX ix_risk_project_id ON control_objectives.risk USING btree (project_id);


--
-- Name: aisc_backend_aicomponent_source_dataset_id_aed18047; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_aicomponent_source_dataset_id_aed18047 ON engine.aisc_backend_aicomponent USING btree (source_dataset_id);


--
-- Name: aisc_backend_aicomponent_system_id_0909bda5; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_aicomponent_system_id_0909bda5 ON engine.aisc_backend_aicomponent USING btree (system_id);


--
-- Name: aisc_backend_artifact_evaluation_plugin_id_a1b64b2e; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_artifact_evaluation_plugin_id_a1b64b2e ON engine.aisc_backend_artifact USING btree (evaluation_plugin_id);


--
-- Name: aisc_backend_derived_base_metric_id_ba6169f6; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_derived_base_metric_id_ba6169f6 ON engine.aisc_backend_derived USING btree (base_metric_id);


--
-- Name: aisc_backend_evaluation_project_id_23e1aa63; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_evaluation_project_id_23e1aa63 ON engine.aisc_backend_evaluation USING btree (project_id);


--
-- Name: aisc_backend_evaluation_system_id_db29add6; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_evaluation_system_id_db29add6 ON engine.aisc_backend_evaluation USING btree (system_id);


--
-- Name: aisc_backend_evaluationinput_component_id_34f724b0; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_evaluationinput_component_id_34f724b0 ON engine.aisc_backend_evaluationinput USING btree (component_id);


--
-- Name: aisc_backend_evaluationinput_evaluation_plugin_id_7c4716b3; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_evaluationinput_evaluation_plugin_id_7c4716b3 ON engine.aisc_backend_evaluationinput USING btree (evaluation_plugin_id);


--
-- Name: aisc_backend_evaluationplugin_evaluation_id_8c122699; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_evaluationplugin_evaluation_id_8c122699 ON engine.aisc_backend_evaluationplugin USING btree (evaluation_id);


--
-- Name: aisc_backend_evaluationplugin_plugin_config_id_61e5a338; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_evaluationplugin_plugin_config_id_61e5a338 ON engine.aisc_backend_evaluationplugin USING btree (plugin_config_id);


--
-- Name: aisc_backend_measurement_metric_id_b7e13397; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_measurement_metric_id_b7e13397 ON engine.aisc_backend_measurement USING btree (metric_id);


--
-- Name: aisc_backend_measurement_observation_id_0bcacda6; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_measurement_observation_id_0bcacda6 ON engine.aisc_backend_measurement USING btree (observation_id);


--
-- Name: aisc_backend_metriccategory_metrics_metric_id_09e83070; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_metriccategory_metrics_metric_id_09e83070 ON engine.aisc_backend_metriccategory_metrics USING btree (metric_id);


--
-- Name: aisc_backend_metriccategory_metrics_metriccategory_id_95f878da; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_metriccategory_metrics_metriccategory_id_95f878da ON engine.aisc_backend_metriccategory_metrics USING btree (metriccategory_id);


--
-- Name: aisc_backend_observation_evaluation_id_b6657f4d; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_observation_evaluation_id_b6657f4d ON engine.aisc_backend_observation USING btree (evaluation_id);


--
-- Name: aisc_backend_plugin_current_config_id_8dec39e8; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_plugin_current_config_id_8dec39e8 ON engine.aisc_backend_plugin USING btree (current_config_id);


--
-- Name: aisc_backend_plugin_project_id_ff74ad16; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_plugin_project_id_ff74ad16 ON engine.aisc_backend_plugin USING btree (project_id);


--
-- Name: aisc_backend_pluginconfig_plugin_id_576d8319; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_pluginconfig_plugin_id_576d8319 ON engine.aisc_backend_pluginconfig USING btree (plugin_id);


--
-- Name: aisc_backend_pluginconfigsetting_plugin_config_id_a7373bb2; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_pluginconfigsetting_plugin_config_id_a7373bb2 ON engine.aisc_backend_pluginconfigprojectconfig USING btree (plugin_config_id);


--
-- Name: aisc_backend_pluginconfigsetting_project_setting_id_2d4a3c74; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_pluginconfigsetting_project_setting_id_2d4a3c74 ON engine.aisc_backend_pluginconfigprojectconfig USING btree (project_config_id);


--
-- Name: aisc_backend_project_platform_project_id_f61734b2; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_project_platform_project_id_f61734b2 ON engine.aisc_backend_project USING btree (project_id);


--
-- Name: aisc_backend_projectsetting_project_id_fedf71b7; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX aisc_backend_projectsetting_project_id_fedf71b7 ON engine.aisc_backend_projectconfig USING btree (project_id);


--
-- Name: metric_dimensions_gin; Type: INDEX; Schema: engine; Owner: -
--

CREATE INDEX metric_dimensions_gin ON engine.aisc_backend_measurement USING gin (dimensions);


--
-- Name: one_project_per_platform_project; Type: INDEX; Schema: engine; Owner: -
--

CREATE UNIQUE INDEX one_project_per_platform_project ON engine.aisc_backend_project USING btree (project_id) WHERE (project_id IS NOT NULL);


--
-- Name: KnowledgeGraph_qualificationId_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX "KnowledgeGraph_qualificationId_key" ON qualification.knowledge_graph USING btree ("qualificationId");


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
-- Name: form_listed_name_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX form_listed_name_key ON qualification.form USING btree (lower(name)) WHERE listed;


--
-- Name: form_question_scope_local_id_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX form_question_scope_local_id_key ON qualification.form_question USING btree (scope, local_id);


--
-- Name: form_version_form_id_number_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX form_version_form_id_number_key ON qualification.form_version USING btree (form_id, number);


--
-- Name: form_version_question_form_version_id_position_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX form_version_question_form_version_id_position_key ON qualification.form_version_question USING btree (form_version_id, "position");


--
-- Name: qualification_answer_qualification_id_tool_id_question_id_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX qualification_answer_qualification_id_tool_id_question_id_key ON qualification.qualification_answer USING btree ("qualificationId", "toolId", "questionId");


--
-- Name: qualification_form_version_id_idx; Type: INDEX; Schema: qualification; Owner: -
--

CREATE INDEX qualification_form_version_id_idx ON qualification.qualification USING btree (form_version_id);


--
-- Name: qualification_system_id_key; Type: INDEX; Schema: qualification; Owner: -
--

CREATE UNIQUE INDEX qualification_system_id_key ON qualification.qualification USING btree (system_id);


--
-- Name: generated_report_layout_idx; Type: INDEX; Schema: report_composer; Owner: -
--

CREATE INDEX generated_report_layout_idx ON report_composer.generated_report USING btree (layout_id, created_at DESC);


--
-- Name: card_component card_component_only_latest_changes; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER card_component_only_latest_changes BEFORE INSERT OR UPDATE ON qualification.card_component FOR EACH ROW EXECUTE FUNCTION qualification.component_only_latest_changes();


--
-- Name: form_version form_builtin_is_fixed; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER form_builtin_is_fixed BEFORE INSERT ON qualification.form_version FOR EACH ROW EXECUTE FUNCTION qualification.form_builtin_is_fixed();


--
-- Name: form form_name_is_fixed; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER form_name_is_fixed BEFORE UPDATE ON qualification.form FOR EACH ROW EXECUTE FUNCTION qualification.form_name_is_fixed();


--
-- Name: form_question form_question_identity_is_fixed; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER form_question_identity_is_fixed BEFORE DELETE OR UPDATE ON qualification.form_question FOR EACH ROW EXECUTE FUNCTION qualification.form_question_identity_is_fixed();


--
-- Name: form_version form_version_is_append_only; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER form_version_is_append_only BEFORE DELETE OR UPDATE ON qualification.form_version FOR EACH ROW EXECUTE FUNCTION qualification.form_version_is_append_only();


--
-- Name: form_version_question form_version_question_is_append_only; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER form_version_question_is_append_only BEFORE DELETE OR UPDATE ON qualification.form_version_question FOR EACH ROW EXECUTE FUNCTION qualification.form_version_question_is_append_only();


--
-- Name: qualification_answer qualification_answer_only_latest_changes; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER qualification_answer_only_latest_changes BEFORE INSERT OR UPDATE ON qualification.qualification_answer FOR EACH ROW EXECUTE FUNCTION qualification.answer_only_latest_changes();


--
-- Name: qualification qualification_only_latest_changes; Type: TRIGGER; Schema: qualification; Owner: -
--

CREATE TRIGGER qualification_only_latest_changes BEFORE UPDATE ON qualification.qualification FOR EACH ROW EXECUTE FUNCTION qualification.qualification_only_latest_changes();


--
-- Name: project fk_project_project_id_core_project; Type: FK CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.project
    ADD CONSTRAINT fk_project_project_id_core_project FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE CASCADE;


--
-- Name: project fk_project_system_id_core_system; Type: FK CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.project
    ADD CONSTRAINT fk_project_system_id_core_system FOREIGN KEY (system_id) REFERENCES core.system(pid) ON DELETE CASCADE;


--
-- Name: project fk_project_system_id_project_id_core_system; Type: FK CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.project
    ADD CONSTRAINT fk_project_system_id_project_id_core_system FOREIGN KEY (system_id, project_id) REFERENCES core.system(pid, project_id) ON DELETE CASCADE;


--
-- Name: graph graph_project_id_fkey; Type: FK CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.graph
    ADD CONSTRAINT graph_project_id_fkey FOREIGN KEY (project_id) REFERENCES control_objectives.project(id) ON DELETE CASCADE;


--
-- Name: mapped_objective mapped_objective_risk_row_id_fkey; Type: FK CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.mapped_objective
    ADD CONSTRAINT mapped_objective_risk_row_id_fkey FOREIGN KEY (risk_row_id) REFERENCES control_objectives.risk(id) ON DELETE CASCADE;


--
-- Name: mapping_run mapping_run_project_id_fkey; Type: FK CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.mapping_run
    ADD CONSTRAINT mapping_run_project_id_fkey FOREIGN KEY (project_id) REFERENCES control_objectives.project(id) ON DELETE CASCADE;


--
-- Name: risk risk_project_id_fkey; Type: FK CONSTRAINT; Schema: control_objectives; Owner: -
--

ALTER TABLE ONLY control_objectives.risk
    ADD CONSTRAINT risk_project_id_fkey FOREIGN KEY (project_id) REFERENCES control_objectives.project(id) ON DELETE CASCADE;


--
-- Name: aisc_backend_aicomponent aisc_backend_aicompo_source_dataset_id_aed18047_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_aicomponent
    ADD CONSTRAINT aisc_backend_aicompo_source_dataset_id_aed18047_fk_aisc_back FOREIGN KEY (source_dataset_id) REFERENCES engine.aisc_backend_aicomponent(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_aicomponent aisc_backend_aicompo_system_id_0909bda5_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_aicomponent
    ADD CONSTRAINT aisc_backend_aicompo_system_id_0909bda5_fk_aisc_back FOREIGN KEY (system_id) REFERENCES engine.aisc_backend_aisystem(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_aisystem aisc_backend_aisystem_project_id_381e09a9_fk_project_id; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_aisystem
    ADD CONSTRAINT aisc_backend_aisystem_project_id_381e09a9_fk_project_id FOREIGN KEY (project_id) REFERENCES engine.aisc_backend_project(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_artifact aisc_backend_artifac_evaluation_plugin_id_a1b64b2e_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_artifact
    ADD CONSTRAINT aisc_backend_artifac_evaluation_plugin_id_a1b64b2e_fk_aisc_back FOREIGN KEY (evaluation_plugin_id) REFERENCES engine.aisc_backend_evaluationplugin(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_derived aisc_backend_derived_base_metric_id_ba6169f6_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_derived
    ADD CONSTRAINT aisc_backend_derived_base_metric_id_ba6169f6_fk_aisc_back FOREIGN KEY (base_metric_id) REFERENCES engine.aisc_backend_metric(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_derived aisc_backend_derived_metric_ptr_id_e8cc6ab1_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_derived
    ADD CONSTRAINT aisc_backend_derived_metric_ptr_id_e8cc6ab1_fk_aisc_back FOREIGN KEY (metric_ptr_id) REFERENCES engine.aisc_backend_metric(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_direct aisc_backend_direct_metric_ptr_id_43d04e07_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_direct
    ADD CONSTRAINT aisc_backend_direct_metric_ptr_id_43d04e07_fk_aisc_back FOREIGN KEY (metric_ptr_id) REFERENCES engine.aisc_backend_metric(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_evaluationinput aisc_backend_evaluat_component_id_34f724b0_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluationinput
    ADD CONSTRAINT aisc_backend_evaluat_component_id_34f724b0_fk_aisc_back FOREIGN KEY (component_id) REFERENCES engine.aisc_backend_aicomponent(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_evaluationplugin aisc_backend_evaluat_evaluation_id_8c122699_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluationplugin
    ADD CONSTRAINT aisc_backend_evaluat_evaluation_id_8c122699_fk_aisc_back FOREIGN KEY (evaluation_id) REFERENCES engine.aisc_backend_evaluation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_evaluationinput aisc_backend_evaluat_evaluation_plugin_id_7c4716b3_fk_evaluatio; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluationinput
    ADD CONSTRAINT aisc_backend_evaluat_evaluation_plugin_id_7c4716b3_fk_evaluatio FOREIGN KEY (evaluation_plugin_id) REFERENCES engine.aisc_backend_evaluationplugin(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_evaluationplugin aisc_backend_evaluat_plugin_config_id_61e5a338_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluationplugin
    ADD CONSTRAINT aisc_backend_evaluat_plugin_config_id_61e5a338_fk_aisc_back FOREIGN KEY (plugin_config_id) REFERENCES engine.aisc_backend_pluginconfig(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_evaluation aisc_backend_evaluat_project_id_23e1aa63_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluation
    ADD CONSTRAINT aisc_backend_evaluat_project_id_23e1aa63_fk_aisc_back FOREIGN KEY (project_id) REFERENCES engine.aisc_backend_project(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_evaluation aisc_backend_evaluation_system_id_fkey; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_evaluation
    ADD CONSTRAINT aisc_backend_evaluation_system_id_fkey FOREIGN KEY (system_id) REFERENCES core.system(pid) ON DELETE SET NULL;


--
-- Name: aisc_backend_measurement aisc_backend_measure_metric_id_b7e13397_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_measurement
    ADD CONSTRAINT aisc_backend_measure_metric_id_b7e13397_fk_aisc_back FOREIGN KEY (metric_id) REFERENCES engine.aisc_backend_metric(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_measurement aisc_backend_measure_observation_id_0bcacda6_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_measurement
    ADD CONSTRAINT aisc_backend_measure_observation_id_0bcacda6_fk_aisc_back FOREIGN KEY (observation_id) REFERENCES engine.aisc_backend_observation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_metriccategory_metrics aisc_backend_metricc_metric_id_09e83070_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_metriccategory_metrics
    ADD CONSTRAINT aisc_backend_metricc_metric_id_09e83070_fk_aisc_back FOREIGN KEY (metric_id) REFERENCES engine.aisc_backend_metric(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_metriccategory_metrics aisc_backend_metricc_metriccategory_id_95f878da_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_metriccategory_metrics
    ADD CONSTRAINT aisc_backend_metricc_metriccategory_id_95f878da_fk_aisc_back FOREIGN KEY (metriccategory_id) REFERENCES engine.aisc_backend_metriccategory(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_observation aisc_backend_observa_evaluation_id_b6657f4d_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_observation
    ADD CONSTRAINT aisc_backend_observa_evaluation_id_b6657f4d_fk_aisc_back FOREIGN KEY (evaluation_id) REFERENCES engine.aisc_backend_evaluation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_plugin aisc_backend_plugin_current_config_id_8dec39e8_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_plugin
    ADD CONSTRAINT aisc_backend_plugin_current_config_id_8dec39e8_fk_aisc_back FOREIGN KEY (current_config_id) REFERENCES engine.aisc_backend_pluginconfig(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_plugin aisc_backend_plugin_project_id_ff74ad16_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_plugin
    ADD CONSTRAINT aisc_backend_plugin_project_id_ff74ad16_fk_aisc_back FOREIGN KEY (project_id) REFERENCES engine.aisc_backend_project(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_pluginconfigprojectconfig aisc_backend_pluginc_plugin_config_id_a7373bb2_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_pluginconfigprojectconfig
    ADD CONSTRAINT aisc_backend_pluginc_plugin_config_id_a7373bb2_fk_aisc_back FOREIGN KEY (plugin_config_id) REFERENCES engine.aisc_backend_pluginconfig(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_pluginconfig aisc_backend_pluginc_plugin_id_576d8319_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_pluginconfig
    ADD CONSTRAINT aisc_backend_pluginc_plugin_id_576d8319_fk_aisc_back FOREIGN KEY (plugin_id) REFERENCES engine.aisc_backend_plugin(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_project aisc_backend_project_platform_project_id_fkey; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_project
    ADD CONSTRAINT aisc_backend_project_platform_project_id_fkey FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE SET NULL;


--
-- Name: aisc_backend_projectconfig aisc_backend_project_project_id_fedf71b7_fk_aisc_back; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_projectconfig
    ADD CONSTRAINT aisc_backend_project_project_id_fedf71b7_fk_aisc_back FOREIGN KEY (project_id) REFERENCES engine.aisc_backend_project(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: aisc_backend_pluginconfigprojectconfig plugin_config_settin_project_config_id_505b7676_fk_project_s; Type: FK CONSTRAINT; Schema: engine; Owner: -
--

ALTER TABLE ONLY engine.aisc_backend_pluginconfigprojectconfig
    ADD CONSTRAINT plugin_config_settin_project_config_id_505b7676_fk_project_s FOREIGN KEY (project_config_id) REFERENCES engine.aisc_backend_projectconfig(id) DEFERRABLE INITIALLY DEFERRED;


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
-- Name: form_question form_question_copied_from_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form_question
    ADD CONSTRAINT form_question_copied_from_id_fkey FOREIGN KEY (copied_from_id) REFERENCES qualification.form_question(id) ON DELETE RESTRICT;


--
-- Name: form_question form_question_owner_form_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form_question
    ADD CONSTRAINT form_question_owner_form_id_fkey FOREIGN KEY (owner_form_id) REFERENCES qualification.form(id) ON DELETE RESTRICT;


--
-- Name: form_version form_version_form_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form_version
    ADD CONSTRAINT form_version_form_id_fkey FOREIGN KEY (form_id) REFERENCES qualification.form(id) ON DELETE RESTRICT;


--
-- Name: form_version_question form_version_question_form_version_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form_version_question
    ADD CONSTRAINT form_version_question_form_version_id_fkey FOREIGN KEY (form_version_id) REFERENCES qualification.form_version(id) ON DELETE RESTRICT;


--
-- Name: form_version_question form_version_question_question_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.form_version_question
    ADD CONSTRAINT form_version_question_question_id_fkey FOREIGN KEY (question_id) REFERENCES qualification.form_question(id) ON DELETE RESTRICT;


--
-- Name: qualification qualification_form_version_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification
    ADD CONSTRAINT qualification_form_version_id_fkey FOREIGN KEY (form_version_id) REFERENCES qualification.form_version(id) ON DELETE RESTRICT;


--
-- Name: qualification qualification_system_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification
    ADD CONSTRAINT qualification_system_id_fkey FOREIGN KEY (system_id) REFERENCES core.system(pid) ON DELETE CASCADE;


--
-- Name: qualification qualification_system_id_project_id_fkey; Type: FK CONSTRAINT; Schema: qualification; Owner: -
--

ALTER TABLE ONLY qualification.qualification
    ADD CONSTRAINT qualification_system_id_project_id_fkey FOREIGN KEY (system_id, project_id) REFERENCES core.system(pid, project_id) ON DELETE CASCADE;


--
-- Name: generated_report generated_report_layout_id_fkey; Type: FK CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.generated_report
    ADD CONSTRAINT generated_report_layout_id_fkey FOREIGN KEY (layout_id) REFERENCES report_composer.layout(id) ON DELETE CASCADE;


--
-- Name: generated_report generated_report_system_id_project_id_fkey; Type: FK CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.generated_report
    ADD CONSTRAINT generated_report_system_id_project_id_fkey FOREIGN KEY (system_id, project_id) REFERENCES core.system(pid, project_id);


--
-- Name: layout_block layout_block_layout_id_fkey; Type: FK CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout_block
    ADD CONSTRAINT layout_block_layout_id_fkey FOREIGN KEY (layout_id) REFERENCES report_composer.layout(id) ON DELETE CASCADE;


--
-- Name: layout layout_project_id_fkey; Type: FK CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout
    ADD CONSTRAINT layout_project_id_fkey FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE CASCADE;


--
-- Name: layout layout_system_id_fkey; Type: FK CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout
    ADD CONSTRAINT layout_system_id_fkey FOREIGN KEY (system_id) REFERENCES core.system(pid);


--
-- Name: layout layout_system_id_project_id_fkey; Type: FK CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout
    ADD CONSTRAINT layout_system_id_project_id_fkey FOREIGN KEY (system_id, project_id) REFERENCES core.system(pid, project_id);


--
-- Name: layout layout_template_id_fkey; Type: FK CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.layout
    ADD CONSTRAINT layout_template_id_fkey FOREIGN KEY (template_id) REFERENCES report_composer.template(id) ON DELETE SET NULL;


--
-- Name: template template_project_id_fkey; Type: FK CONSTRAINT; Schema: report_composer; Owner: -
--

ALTER TABLE ONLY report_composer.template
    ADD CONSTRAINT template_project_id_fkey FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


-- core functions used by the moving schemas
CREATE OR REPLACE FUNCTION core.system_only_latest_changes()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.number <> OLD.number OR NEW.project_id <> OLD.project_id
     OR OLD.number < (SELECT max(number) FROM core.system WHERE project_id = OLD.project_id) THEN
    RAISE EXCEPTION 'system version % of project % is not the latest and cannot change',
      OLD.number, OLD.project_id;
  END IF;
  RETURN NEW;
END $function$
;
