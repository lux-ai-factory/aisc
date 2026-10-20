"""The composer is opened from step 4 on the launcher, Collect evidence, so "← Collect evidence"
goes one level up, to that page; the mark still goes to the project's page. No database."""
from report_composer.jinja_env import env

PID = "01399e17-4b01-4be9-997a-7f5e3574ab22"


def _header(project):
    return env.get_template("base.html.j2").render(project=project, root="/report-composer", here="layouts")


def test_back_returns_to_collect_evidence():
    html = _header({"pid": PID, "slug": "demo"})
    assert (f'<a href="{env.globals["launcher"]}evidence.html?project={PID}" '
            'aria-label="Back to Collect evidence">&larr; Collect evidence</a>') in html
    assert f'class="brand" href="{env.globals["launcher"]}p/{PID}"' in html


def test_without_a_project_there_is_no_back():
    assert "&larr; Collect evidence" not in _header(None)


def test_the_navigation_names_the_report_layouts_and_looks():
    html = _header({"pid": PID, "slug": "demo"})
    assert ">Report layouts</a>" in html and ">Report looks</a>" in html
    assert ">Reports</a>" not in html and ">Templates</a>" not in html
