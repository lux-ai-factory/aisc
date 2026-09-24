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
-- Name: control_objectives; Type: SCHEMA; Schema: -; Owner: -
--



--
-- Name: SCHEMA control_objectives; Type: COMMENT; Schema: -; Owner: -
--



SET default_tablespace = '';


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
-- PostgreSQL database dump complete
--


