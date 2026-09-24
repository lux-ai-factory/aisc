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
-- Name: controls; Type: SCHEMA; Schema: -; Owner: -
--



--
-- Name: SCHEMA controls; Type: COMMENT; Schema: -; Owner: -
--



--
-- Name: SubmissionStatus; Type: TYPE; Schema: controls; Owner: -
--

CREATE TYPE controls."SubmissionStatus" AS ENUM (
    'Draft',
    'Closed'
);


SET default_tablespace = '';


--
-- Name: _prisma_migrations; Type: TABLE; Schema: controls; Owner: -
--

CREATE TABLE controls._prisma_migrations (
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
-- Name: checklist; Type: TABLE; Schema: controls; Owner: -
--

CREATE TABLE controls.checklist (
    id text NOT NULL,
    "catalogueId" text,
    title text NOT NULL,
    "sourceId" text NOT NULL,
    source_updated_at timestamp(3) with time zone,
    "countryIds" text[] DEFAULT ARRAY[]::text[],
    "regulationIds" text[] DEFAULT ARRAY[]::text[],
    "controlTopic" text NOT NULL,
    description text,
    created_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) with time zone NOT NULL
);


--
-- Name: checklist_question; Type: TABLE; Schema: controls; Owner: -
--

CREATE TABLE controls.checklist_question (
    id text NOT NULL,
    "checklistId" text NOT NULL,
    "order" integer NOT NULL,
    text text NOT NULL,
    article text,
    category text
);


--
-- Name: source; Type: TABLE; Schema: controls; Owner: -
--

CREATE TABLE controls.source (
    id text NOT NULL,
    slug text NOT NULL,
    name text NOT NULL,
    citation text,
    url text,
    created_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) with time zone NOT NULL
);


--
-- Name: submission; Type: TABLE; Schema: controls; Owner: -
--

CREATE TABLE controls.submission (
    id text NOT NULL,
    "checklistId" text NOT NULL,
    label text NOT NULL,
    status controls."SubmissionStatus" DEFAULT 'Draft'::controls."SubmissionStatus" NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    "previousVersionId" text,
    closed_at timestamp(3) with time zone,
    archived_at timestamp(3) with time zone,
    created_at timestamp(3) with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) with time zone NOT NULL
);


--
-- Name: submission_answer; Type: TABLE; Schema: controls; Owner: -
--

CREATE TABLE controls.submission_answer (
    id text NOT NULL,
    "submissionId" text NOT NULL,
    "questionId" text NOT NULL,
    answer text,
    score integer,
    system_version_pid uuid,
    system_version_number integer,
    answered_at timestamp(3) with time zone
);


--
-- Name: _prisma_migrations _prisma_migrations_pkey; Type: CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls._prisma_migrations
    ADD CONSTRAINT _prisma_migrations_pkey PRIMARY KEY (id);


--
-- Name: checklist checklist_pkey; Type: CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.checklist
    ADD CONSTRAINT checklist_pkey PRIMARY KEY (id);


--
-- Name: checklist_question checklist_question_pkey; Type: CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.checklist_question
    ADD CONSTRAINT checklist_question_pkey PRIMARY KEY (id);


--
-- Name: source source_pkey; Type: CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.source
    ADD CONSTRAINT source_pkey PRIMARY KEY (id);


--
-- Name: submission_answer submission_answer_pkey; Type: CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.submission_answer
    ADD CONSTRAINT submission_answer_pkey PRIMARY KEY (id);


--
-- Name: submission submission_pkey; Type: CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.submission
    ADD CONSTRAINT submission_pkey PRIMARY KEY (id);


--
-- Name: checklist_catalogueId_key; Type: INDEX; Schema: controls; Owner: -
--

CREATE UNIQUE INDEX "checklist_catalogueId_key" ON controls.checklist USING btree ("catalogueId");


--
-- Name: checklist_question_checklistId_idx; Type: INDEX; Schema: controls; Owner: -
--

CREATE INDEX "checklist_question_checklistId_idx" ON controls.checklist_question USING btree ("checklistId");


--
-- Name: checklist_question_checklistId_order_key; Type: INDEX; Schema: controls; Owner: -
--

CREATE UNIQUE INDEX "checklist_question_checklistId_order_key" ON controls.checklist_question USING btree ("checklistId", "order");


--
-- Name: checklist_sourceId_idx; Type: INDEX; Schema: controls; Owner: -
--

CREATE INDEX "checklist_sourceId_idx" ON controls.checklist USING btree ("sourceId");


--
-- Name: source_name_key; Type: INDEX; Schema: controls; Owner: -
--

CREATE UNIQUE INDEX source_name_key ON controls.source USING btree (name);


--
-- Name: source_slug_key; Type: INDEX; Schema: controls; Owner: -
--

CREATE UNIQUE INDEX source_slug_key ON controls.source USING btree (slug);


--
-- Name: submission_answer_submissionId_idx; Type: INDEX; Schema: controls; Owner: -
--

CREATE INDEX "submission_answer_submissionId_idx" ON controls.submission_answer USING btree ("submissionId");


--
-- Name: submission_answer_submissionId_questionId_key; Type: INDEX; Schema: controls; Owner: -
--

CREATE UNIQUE INDEX "submission_answer_submissionId_questionId_key" ON controls.submission_answer USING btree ("submissionId", "questionId");


--
-- Name: submission_archived_at_idx; Type: INDEX; Schema: controls; Owner: -
--

CREATE INDEX submission_archived_at_idx ON controls.submission USING btree (archived_at);


--
-- Name: submission_checklistId_idx; Type: INDEX; Schema: controls; Owner: -
--

CREATE INDEX "submission_checklistId_idx" ON controls.submission USING btree ("checklistId");


--
-- Name: submission_previousVersionId_key; Type: INDEX; Schema: controls; Owner: -
--

CREATE UNIQUE INDEX "submission_previousVersionId_key" ON controls.submission USING btree ("previousVersionId");


--
-- Name: submission_status_idx; Type: INDEX; Schema: controls; Owner: -
--

CREATE INDEX submission_status_idx ON controls.submission USING btree (status);


--
-- Name: checklist_question checklist_question_checklistId_fkey; Type: FK CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.checklist_question
    ADD CONSTRAINT "checklist_question_checklistId_fkey" FOREIGN KEY ("checklistId") REFERENCES controls.checklist(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: checklist checklist_sourceId_fkey; Type: FK CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.checklist
    ADD CONSTRAINT "checklist_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES controls.source(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: submission_answer submission_answer_questionId_fkey; Type: FK CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.submission_answer
    ADD CONSTRAINT "submission_answer_questionId_fkey" FOREIGN KEY ("questionId") REFERENCES controls.checklist_question(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: submission_answer submission_answer_submissionId_fkey; Type: FK CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.submission_answer
    ADD CONSTRAINT "submission_answer_submissionId_fkey" FOREIGN KEY ("submissionId") REFERENCES controls.submission(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: submission submission_checklistId_fkey; Type: FK CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.submission
    ADD CONSTRAINT "submission_checklistId_fkey" FOREIGN KEY ("checklistId") REFERENCES controls.checklist(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: submission submission_previousVersionId_fkey; Type: FK CONSTRAINT; Schema: controls; Owner: -
--

ALTER TABLE ONLY controls.submission
    ADD CONSTRAINT "submission_previousVersionId_fkey" FOREIGN KEY ("previousVersionId") REFERENCES controls.submission(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--


