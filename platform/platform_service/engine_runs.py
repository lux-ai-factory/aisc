"""Which of the engine's runs belong to a project's assessment record, as SQL the platform's readers of the
engine's tables share (evidence.py, dashboards.py), so the sandbox tiles and the dashboards count the same runs.

The predicates name the engine's tables by the aliases every reader gives them: `e` for
engine.aisc_backend_evaluation, `ep` for engine.aisc_backend_evaluationplugin."""
from __future__ import annotations

#: An archived evaluation is hidden in the engine, so it is not counted.
NOT_ARCHIVED = "e.status <> 'Archived'"
#: A run on a local model file: the engine worker stores {"local_model": {"file", "sha256"}} as the value of
#: the plugin's model input (an evaluationinput `li`). It is not part of the assessment record: never counted
#: with the AI card's runs, whatever else it has, and listed apart. A local_model that is not an object is not
#: that marker, and the run is an ordinary one.
IS_LOCAL_INPUT = "jsonb_typeof(li.value->'local_model') = 'object'"
LOCAL = ("EXISTS (SELECT 1 FROM engine.aisc_backend_evaluationinput li"
         " WHERE li.evaluation_plugin_id = ep.id AND " + IS_LOCAL_INPUT + ")")
NOT_LOCAL = "NOT " + LOCAL
