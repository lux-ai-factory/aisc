"""The modules' stand-in for the content a check is given on: the card, a checklist submission's answers and
a card version's risk register, with the column names the apps use, made and written as the throwaway's
superuser. platform_rw gets exactly what the apps' migrations grant it to compute a content hash
(test_content_hash.py checks the two agree)."""
from __future__ import annotations

import os

import psycopg
from psycopg.conninfo import make_conninfo

from platform_service import projectdb

SUPERUSER = os.environ.get("PLATFORM_TEST_SUPERUSER_URL", "")

TABLES = """
CREATE TABLE IF NOT EXISTS qualification.qualification (
    id text PRIMARY KEY, system_id uuid NOT NULL, revision int NOT NULL DEFAULT 1, "ontologyPatch" jsonb,
    "systemName" text NOT NULL DEFAULT 'S', "systemVersion" text NOT NULL DEFAULT '',
    company text NOT NULL DEFAULT '', description text NOT NULL DEFAULT '', saved_by text, amended_by text,
    created_at timestamptz NOT NULL DEFAULT now(), "targetUseCase" text NOT NULL DEFAULT '',
    "targetUsers" text NOT NULL DEFAULT '', "intendedDeployers" text, system_type text, purpose text,
    provider_term text, deployer_term text, "targetSystemTags" text[] NOT NULL DEFAULT '{}',
    "sectorTags" text[] NOT NULL DEFAULT '{}', "marketFormTags" text[] NOT NULL DEFAULT '{}',
    "localityTags" text[] NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS qualification.qualification_answer (
    id text PRIMARY KEY DEFAULT gen_random_uuid()::text, "qualificationId" text NOT NULL, "toolId" text NOT NULL,
    "questionId" text NOT NULL, answer text NOT NULL);
CREATE TABLE IF NOT EXISTS qualification.qualification_component (
    id text PRIMARY KEY DEFAULT gen_random_uuid()::text, qualification_id text NOT NULL, position int NOT NULL,
    key uuid NOT NULL, name text NOT NULL, role text, kind text NOT NULL, vair_type text,
    provider text NOT NULL DEFAULT 'in_house', provider_name text);
CREATE TABLE IF NOT EXISTS qualification.qualification_risk (
    id text PRIMARY KEY DEFAULT gen_random_uuid()::text, "qualificationId" text NOT NULL, position int NOT NULL,
    risk text NOT NULL, source text NOT NULL, source_term text, vulnerability text, consequence text NOT NULL,
    consequence_term text, impact_term text, affected text NOT NULL, "impactAreas" text[] DEFAULT '{}');
CREATE TABLE IF NOT EXISTS controls.submission_answer (
    id text PRIMARY KEY DEFAULT gen_random_uuid()::text, "submissionId" text NOT NULL, "questionId" text,
    answer text, score int, answered_at timestamptz);
CREATE TABLE IF NOT EXISTS control_objectives.project (
    id varchar(32) PRIMARY KEY, name text NOT NULL DEFAULT 'a', system_id uuid NOT NULL);
CREATE TABLE IF NOT EXISTS control_objectives.risk (
    id serial PRIMARY KEY, project_id varchar(32) NOT NULL, risk_id text NOT NULL, text text NOT NULL DEFAULT 'r',
    rating_impact int, rating_likelihood int, severity_comment text NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS control_objectives.mapped_objective (
    id serial PRIMARY KEY, risk_row_id int NOT NULL, objective_id text NOT NULL, quote text NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS control_objectives.objective_key (
    project_id varchar(32) NOT NULL, objective_id text NOT NULL, key boolean NOT NULL,
    PRIMARY KEY (project_id, objective_id));
"""

#: what the apps' migrations grant platform_rw for the content hashes, one statement per table
GRANTS = (
    'GRANT SELECT (id, system_id, revision, "ontologyPatch") ON qualification.qualification TO platform_rw;',
    'GRANT SELECT (saved_by, amended_by, created_at) ON qualification.qualification TO platform_rw;',
    'GRANT SELECT ("systemName", "systemVersion", company, description) ON qualification.qualification TO platform_rw;',
    'GRANT SELECT ("targetUseCase", "targetUsers", "intendedDeployers", system_type, purpose, provider_term,'
    ' deployer_term, "targetSystemTags", "sectorTags", "marketFormTags", "localityTags")'
    ' ON qualification.qualification TO platform_rw;',
    'GRANT SELECT ("qualificationId", "toolId", "questionId", answer) ON qualification.qualification_answer'
    ' TO platform_rw;',
    'GRANT SELECT (qualification_id, position, key, name, role, kind, vair_type, provider, provider_name)'
    ' ON qualification.qualification_component TO platform_rw;',
    'GRANT SELECT ("qualificationId", position, risk, source, source_term, vulnerability, consequence,'
    ' consequence_term, impact_term, affected, "impactAreas") ON qualification.qualification_risk TO platform_rw;',
    'GRANT SELECT ("submissionId", "questionId", answer, score) ON controls.submission_answer TO platform_rw;',
    'GRANT SELECT (id, system_id) ON control_objectives.project TO platform_rw;',
    'GRANT SELECT (id, project_id, risk_id, rating_impact, rating_likelihood, severity_comment)'
    ' ON control_objectives.risk TO platform_rw;',
    'GRANT SELECT (risk_row_id, objective_id) ON control_objectives.mapped_objective TO platform_rw;',
    'GRANT SELECT (project_id, objective_id, key) ON control_objectives.objective_key TO platform_rw;',
)


def sql(project, statement, params=()):
    """`statement` in the project's database as the superuser; the rows when it answers any."""
    pid = project["pid"] if isinstance(project, dict) else project
    with psycopg.connect(make_conninfo(SUPERUSER, dbname=projectdb.database_name(pid))) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else None


def make_tables(project) -> None:
    sql(project, TABLES + "\n".join(GRANTS))


def card_version(project, pid: str, number: int) -> str:
    sql(project, "INSERT INTO project.system (pid, number, name) VALUES (%s, %s, 'S')", (pid, number))
    return pid


def card(project, card_id: str, version: str, revision: int = 1, answers=(("annex-1", "q1", "Hiring"),),
         patch=None) -> str:
    sql(project, 'INSERT INTO qualification.qualification (id, system_id, revision, "ontologyPatch")'
                 ' VALUES (%s, %s, %s, %s)', (card_id, version, revision, None if patch is None else
                                             psycopg.types.json.Jsonb(patch)))
    for tool, question, answer in answers:
        sql(project, 'INSERT INTO qualification.qualification_answer ("qualificationId", "toolId", "questionId",'
                     ' answer) VALUES (%s, %s, %s, %s)', (card_id, tool, question, answer))
    return card_id
