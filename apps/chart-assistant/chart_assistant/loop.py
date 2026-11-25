"""One conversation with the model. The model reads the description of the project's data (never its rows), may run
queries on the mock database, and ends a request with a chart proposal: its query, its settings, what it computes.

Every query passes query_check before it runs or is proposed (R4, R5). The model never writes a number shown in a
chart (R2): it proposes a query; the values are computed by the mock database now and by the real one after
validation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Callable

from chart_assistant.proposal_check import result_problem, unknown_keys
from chart_assistant.query_check import QueryRefused, check, fingerprint
from chart_assistant.views import expand

#: the kinds a plot can switch between in place, keeping its query (the dashboard's changed_params says the same)
IN_PLACE_KINDS = ("bar", "line")
KINDS = ("radar", *IN_PLACE_KINDS, "table")
#: what change_chart may name; the dashboard says which of them each plot takes (its can_change)
CHANGES = {"title": {"type": "string"}, "kind": {"type": "string", "enum": list(IN_PLACE_KINDS)},
           "axis_min": {"type": "number"}, "axis_max": {"type": "number"}, "percent": {"type": "boolean"}}
MOCK_ROWS_TO_MODEL = 50

SYSTEM = """You build charts for an AI assessment tool, as SQL queries on a PostgreSQL database and chart settings.
You never see the real data: run_on_mock runs a query on a mock database with the same tables and invented rows, so
you can check that your query runs and returns the shape you want.

You add plots, change plots and remove plots. Each request comes with every plot on this dashboard: its number,
title, kind, whether you made it, and its definition (how it is built: axes, series, value, filters, scale; never its
values). Read the definitions first: when the request is about a plot that is already there, change that plot, never
add a new one beside it. When several plots could match the request, ask which one: two plots that show the same thing
(the same value along the same axes, or alike titles) both match, whoever made them, so name them both in the question. You answer the person in exactly
one of these ways, and never in any other:
- change_chart, to change a plot in place: its title, its kind between bar and line, the minimum or maximum of its
  axis (a radar's maximum on every axis), percentages on or off. It is done at once;
- propose_chart, for a new plot, or for a change that needs a different query: set replaces to the plot it replaces,
  which takes the old plot's place once the person validates it;
- remove_chart, only when the person clearly asks to delete or remove plots and it is clear which ones: call it once
  per plot (all of them in the same answer for "delete all ..."); they are removed at once, without asking again;
- ask_question, when something you need is unclear (which plot, whether they mean delete, which metric, which runs,
  which models, how to group): one short question, at most two sentences, in plain words.
Never change the values to change how a plot looks: a scale, a range or a unit is a setting of the plot (change_chart),
never arithmetic in the query.
Never write text outside these tools: no numbers, rows, results, SQL, explanations or summaries for the person. The
mock rows are invented, so never report them. Ask only when you cannot choose sensibly yourself; otherwise act.

A chart's query returns columns named in its settings:
- category: the axis (radar axes, bar or line x values),
- series: one polygon, bar group or line per value (optional),
- value: the number shown.
Kinds: radar, bar, line, table. Write the chart's description in one or two plain sentences: what each value is and how
it is computed, so a person can judge it without reading SQL. Never invent numbers.

Read from the view results whenever it holds what you need; use the other tables only for what it lacks. What was
tested (a back-end, a model, a component) is a target: results.target, never a dimension. A metric's dimensions hold
only the keys listed for it below. Results include runs that did not finish (run_status other than 'Done'): keep
them unless the person asks for finished runs only, and say in the description which runs the chart counts.

The project's data model follows.

"""

TOOLS = [
    {"type": "function", "function": {
        "name": "run_on_mock", "description": "Run a read-only query on the mock database (invented rows) and see its first rows.",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "propose_chart", "description": "Propose the chart to the person.",
        "parameters": {"type": "object", "required": ["sql", "chart", "description"], "properties": {
            "sql": {"type": "string"},
            "description": {"type": "string"},
            "chart": {"type": "object", "required": ["kind", "title", "category", "value"], "properties": {
                "kind": {"type": "string", "enum": list(KINDS)}, "title": {"type": "string"},
                "category": {"type": "string"}, "series": {"type": "string"}, "value": {"type": "string"}}},
            "replaces": {"type": "integer", "description": "the number of the plot this one replaces"},
            "near": {"type": "integer", "description": "the number of the plot this new one belongs beside, when the "
                                                       "person asked about that plot"}}}}},
    {"type": "function", "function": {
        "name": "change_chart", "description": "Change a plot on the dashboard in place, without changing its query.",
        "parameters": {"type": "object", "required": ["chart", "changes"], "properties": {
            "chart": {"type": "integer"},
            "changes": {"type": "object", "properties": CHANGES}}}}},
    {"type": "function", "function": {
        "name": "remove_chart", "description": "Remove a plot from the dashboard, when the person clearly asked.",
        "parameters": {"type": "object", "properties": {"chart": {"type": "integer"}}, "required": ["chart"]}}},
    {"type": "function", "function": {
        "name": "ask_question", "description": "Ask the person one short question when the request is unclear.",
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
]


#: words with which a person asks to delete, in the languages people use here: without one of them in the request, no
#: plot is removed, whatever the model decides (it once removed a plot when asked to change a scale)
DELETE_WORDS = re.compile(r"\b(delet\w*|remov\w*|erase\w*|get rid|elimin\w*|cancell\w*|togl\w*|tolg\w*|"
                          r"rimuov\w*|rimoss\w*|verwijder\w*|supprim\w*|effac\w*|lösch\w*)", re.IGNORECASE)

#: words that name a kind of plot in a request (English, Italian, Dutch)
_KIND_WORDS = {"bar": {"bar", "bars", "barre", "barra", "staaf", "staven"},
               "line": {"line", "lines", "linea", "linee", "lijn"},
               "radar": {"radar", "radars", "ragno"}, "table": {"table", "tabella", "tabel"}}


def _title_words(title: str) -> set:
    return {w for w in re.findall(r"[^\W\d_]+", str(title or "").lower()) if len(w) >= 3}


def _alike(plot: dict, plots, request: str) -> list[dict]:
    """The other plots the dashboard says are alike (its same_as) that the request does not tell apart from this one:
    by its number, a word naming its kind when the other is of another kind, or a title word only it has. When any is
    left, the model must ask which one."""
    asked = set(re.findall(r"[^\W_]+", request.lower()))
    if str(plot["id"]) in asked:
        return []
    alike, left = set(plot.get("same_as") or []), []
    for other in plots:
        if other["id"] not in alike or other["id"] == plot["id"]:
            continue
        if other.get("kind") != plot.get("kind") and asked & _KIND_WORDS.get(plot.get("kind"), set()):
            continue
        if asked & (_title_words(plot.get("title")) - _title_words(other.get("title"))):
            continue
        left.append(other)
    return left


#: the longest question shown to the person; longer means the model is reporting, not asking
MAX_QUESTION = 300
ONLY_TOOLS = ("Not shown to the person. Answer only by calling ask_question (one short question) or propose_chart "
              "(the chart); never write text of your own.")


class BudgetSpent(RuntimeError):
    """The conversation or the request used its allowance."""


@dataclass
class Proposal:
    sql: str
    chart: dict
    description: str
    mock: dict
    fingerprint: str
    replaces: int | None = None
    replaces_title: str | None = None
    #: the plot of the dashboard this new one belongs beside
    near: int | None = None
    #: its number in the conversation: two proposals may share a query (bars, then lines)
    number: int = 0


@dataclass
class Change:
    """A plot changed in place (settings, never its query); the dashboard makes the change."""
    chart: int
    title: str
    changes: dict


@dataclass
class Removal:
    """The plots the person clearly asked to remove, as (number, title); the dashboard takes them off."""
    charts: list


def _made_text(charts) -> str:
    if not charts:
        return "\n\n(There are no plots on this dashboard.)"
    def line(c):
        made = f"made by you, query: {c.get('sql')}" if c.get("mine", True) else "not made by you"
        built = f"; definition: {json.dumps(c['definition'], ensure_ascii=False)}" if c.get("definition") else ""
        return f"- plot {c['id']}: {c.get('title')!r} ({c.get('kind')}), {made}{built}"
    lines = [line(c) for c in charts]
    return "\n\n(Plots on this dashboard:\n" + "\n".join(lines) + ")"


def _chart_problem(chart, columns) -> str | None:
    if not isinstance(chart, dict) or chart.get("kind") not in KINDS:
        return f"chart.kind must be one of {', '.join(KINDS)}"
    for key in ("title", "category", "value"):
        if not isinstance(chart.get(key), str) or not chart[key]:
            return f"chart.{key} is required"
    for key in ("category", "series", "value"):
        if chart.get(key) and chart[key] not in columns:
            return f"chart.{key} {chart[key]!r} is not a column of the query's result ({', '.join(columns)})"
    return None


class Conversation:
    def __init__(self, *, description: str, readers, model: Callable, run_on_mock: Callable[[str], dict],
                 views: dict | None = None, known_keys: frozenset[str] | None = None,
                 max_steps: int = 8, max_messages: int = 30):
        self.readers, self.model, self.run_on_mock = set(readers), model, run_on_mock
        #: the views a query may read by name (written in before it runs), and the dimension keys the project's results
        #: have (None: not checked)
        self.views, self.known_keys = dict(views or {}), known_keys
        self.max_steps, self.max_messages = max_steps, max_messages
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM + description}]
        self.asked = 0
        self.proposals: list[Proposal] = []
        self.made: dict[int, dict] = {}
        self.request = ""
        #: the person asked to delete: set by the request whose words say so (DELETE_WORDS) and kept through the answer to
        #: the model's next question (which plot?), so the answer "the scaled one" removes it
        self.delete_asked = False
        self._delete_said = False
        #: the request answers the question the model asked last: it says which plot
        self.answered = False
        self._asked_last = False

    def state(self) -> dict:
        """What the conversation must remember to go on after a restart, as plain JSON: what the model was sent (the
        description is in the system message: labels, never rows), the counters, the flags and the proposals."""
        return {"messages": json.loads(json.dumps(self.messages)), "asked": self.asked,
                "proposals": [asdict(p) for p in self.proposals],
                "delete_asked": self.delete_asked, "delete_said": self._delete_said,
                "answered": self.answered, "asked_last": self._asked_last}

    @classmethod
    def restored(cls, state: dict, **kwargs) -> "Conversation":
        """The conversation rebuilt from its state; kwargs are the constructor's. The state's system message is kept, not
        rebuilt, so the model goes on reading what it read before."""
        c = cls(**kwargs)
        c.messages = list(state["messages"])
        c.asked = int(state["asked"])
        c.proposals = [Proposal(**p) for p in state["proposals"]]
        c.delete_asked, c._delete_said = bool(state["delete_asked"]), bool(state["delete_said"])
        c.answered, c._asked_last = bool(state["answered"]), bool(state["asked_last"])
        return c

    def _plot(self, number) -> dict | None:
        """The plot with that number on this dashboard; true or false is not a number (bool is an int in Python)."""
        return self.made.get(number) if type(number) is int else None

    def _run(self, sql: str) -> tuple[str, dict]:
        """The query as it runs (the views it reads written in) and its result on the mock database."""
        check(sql, self.readers, views=frozenset(self.views))
        full = expand(sql, self.views)
        check(full, self.readers)
        return full, self.run_on_mock(full)

    def _tool(self, call) -> tuple[str, Proposal | str | None]:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            return "Refused: the arguments are not JSON.", None
        if not isinstance(args, dict):
            return "Refused: the arguments must be a JSON object.", None
        if name == "ask_question":
            question = str(args.get("question") or "").strip()
            if "?" not in question or len(question) > MAX_QUESTION:
                return (f"Refused: ask one short question (with a '?'), at most {MAX_QUESTION} characters; "
                        "never results or explanations."), None
            return "Shown to the person.", question
        if name in ("change_chart", "remove_chart") and not self.answered:
            plot = self._plot(args.get("chart"))
            alike = _alike(plot, self.made.values(), self.request) if plot else []
            if alike:
                names = "; ".join(f"plot {p['id']} {p.get('title')!r}" for p in [plot, *alike])
                return f"Refused: these plots show the same thing: {names}. Ask the person which one, naming them.", None
        if name == "change_chart":
            plot = self._plot(args.get("chart"))
            if plot is None:
                return "Refused: you may only change a plot on this dashboard (see the list).", None
            changes, allowed = args.get("changes"), list(plot.get("can_change") or [])
            if not isinstance(changes, dict) or not changes:
                return "Refused: say what to change.", None
            # the dashboard says what each plot can change in place, and checks the values when it makes the change
            if set(changes) - set(allowed):
                return (f"Refused: plot {plot['id']} can change only {', '.join(allowed) or 'nothing'} in place; anything "
                        "else needs a new query (propose_chart with replaces)."), None
            return "Changed.", Change(chart=plot["id"], title=str(plot.get("title") or ""), changes=dict(args["changes"]))
        if name == "remove_chart":
            if not self.delete_asked:
                return ("Refused: the person did not ask to delete anything. Do what they asked (change_chart for a "
                        "scale or a kind), or ask."), None
            made = self._plot(args.get("chart"))
            if made is None:
                return "Refused: you may only remove a plot on this dashboard (see the list).", None
            return "Removed.", Removal(charts=[(made["id"], str(made.get("title") or ""))])
        replaced = None
        if name == "propose_chart" and args.get("replaces") is not None:
            replaced = self._plot(args["replaces"])
            if replaced is None:
                return "Refused: replaces must be the number of a plot on this dashboard (see the list).", None
        neighbour = None
        if name == "propose_chart" and args.get("near") is not None:
            neighbour = self._plot(args["near"])
            if neighbour is None:
                return "Refused: near must be the number of a plot on this dashboard (see the list).", None
        # a closing semicolon breaks the query once it is wrapped as a dataset on the real data
        sql = re.sub(r"[\s;]+$", "", str(args.get("sql") or ""))
        if self.known_keys is not None:
            try:
                unknown = unknown_keys(sql, self.known_keys)
            except Exception:                                    # noqa: BLE001 - unreadable: query_check says why
                unknown = []
            if unknown:
                return (f"Refused: this project's results have no dimension key {', '.join(repr(k) for k in unknown)}. "
                        f"The keys are: {', '.join(sorted(self.known_keys))}. What was tested is results.target."), None
        try:
            sql, result = self._run(sql)
        except QueryRefused as refused:
            return f"Refused: {refused}", None
        except Exception as failed:                                  # noqa: BLE001 - the model may fix its query
            return f"The query failed on the mock database: {str(failed)[:300]}", None
        if name == "run_on_mock":
            return json.dumps({"columns": result["columns"], "rows": result["rows"][:MOCK_ROWS_TO_MODEL]}, default=str), None
        if name == "propose_chart":
            problem = _chart_problem(args.get("chart"), result["columns"])
            if problem:
                return f"Not a valid chart: {problem}", None
            problem = result_problem(args["chart"], result)
            if problem:
                return f"Refused: {problem}.", None
            return "Shown to the person.", Proposal(sql=sql, chart=args["chart"], description=str(args.get("description") or ""),
                                                    mock=result, fingerprint=fingerprint(sql),
                                                    replaces=replaced["id"] if replaced else None,
                                                    replaces_title=str(replaced.get("title") or "") if replaced else None,
                                                    near=neighbour["id"] if neighbour else None)
        return f"Refused: no tool {name}", None

    def ask(self, text: str, charts=None) -> Proposal | Change | Removal | str:
        """The person's request; a Proposal, or the model's question back. Text the model writes outside its tools never
        reaches the person: it is sent back with the rule, and counts as a step."""
        if self.asked >= self.max_messages:
            raise BudgetSpent(f"this conversation has used its {self.max_messages} messages")
        self.asked += 1
        self.request = text
        self.answered, self._asked_last = self._asked_last, False
        said = bool(DELETE_WORDS.search(text))
        self.delete_asked, self._delete_said = said or (self.answered and self._delete_said), said
        self.made = {c["id"]: c for c in (charts or []) if isinstance(c, dict) and isinstance(c.get("id"), int)}
        self.messages.append({"role": "user", "content": text + _made_text(list(self.made.values()))})
        for _ in range(self.max_steps):
            reply = self.model(self.messages, TOOLS)
            self.messages.append(reply)
            calls = reply.get("tool_calls") or []
            if not calls:
                self.messages.append({"role": "user", "content": ONLY_TOOLS})
                continue
            proposal, question, removal, change = None, None, None, None
            for call in calls:
                answer, made = self._tool(call)
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": answer})
                if isinstance(made, Proposal):
                    proposal = made
                elif isinstance(made, Change):
                    change = made
                elif isinstance(made, Removal):
                    removal = Removal(charts=[*(removal.charts if removal else []),
                                              *(c for c in made.charts if c not in (removal.charts if removal else []))])
                elif isinstance(made, str):
                    question = made
            if proposal is not None:
                proposal.number = len(self.proposals) + 1
                self.proposals.append(proposal)
                return proposal
            if removal is not None:
                return removal
            if change is not None:
                return change
            if question is not None:
                self._asked_last = True
                return question
        raise BudgetSpent(f"no chart after {self.max_steps} steps: ask again more precisely")
