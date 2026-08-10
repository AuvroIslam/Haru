"""Tests for the live run view and CLI (PRD §4.17)."""

import json
import threading

import pytest
from fastapi.testclient import TestClient

from haru.api.app import create_app
from haru.api.runs import RunManager, RunRecord, sse, stream
from haru.cli import build_parser, main
from haru.execution.actions import Action, ActionType
from haru.execution.executor import FakeExecutor
from haru.execution.loop import AgentLoop, ScriptedDecider, Step
from haru.execution.page import Element, ElementRole


def elements() -> list[Element]:
    return [
        Element(index=0, role=ElementRole.TEXTBOX, label="Full name", selector="#n", tag="input"),
        Element(index=1, role=ElementRole.TEXTBOX, label="Email", selector="#e", tag="input"),
    ]


def fill(target: int, value: str) -> Action:
    return Action(action_type=ActionType.FILL, target=target, value=value)


@pytest.fixture
def runs():
    return RunManager()


@pytest.fixture
def client(runs):
    return TestClient(create_app(runs=runs))


class TestStepStreaming:
    """The loop must report progress as it happens, not only at the end."""

    def test_on_step_fires_per_turn(self):
        seen: list[Step] = []
        executor = FakeExecutor(elements())
        AgentLoop(
            executor,
            ScriptedDecider([fill(0, "Ada"), fill(1, "ada@example.com")]),
            on_step=seen.append,
        ).run()
        assert len(seen) == 2
        assert seen[0].action.value == "Ada"

    def test_steps_arrive_before_the_run_finishes(self):
        executor = FakeExecutor(elements())
        during: list[int] = []

        class Counting:
            def __init__(self):
                self.queue = [fill(0, "a"), fill(1, "b")]

            def decide(self, snapshot, notes):
                during.append(len(seen))
                return [self.queue.pop(0)] if self.queue else []

        seen: list[Step] = []
        AgentLoop(executor, Counting(), on_step=seen.append).run()

        # One more entry than actions: the final call is the loop asking for a
        # next action and being told there is none. The property under test is
        # that the count rises between turns — step N reaches the observer
        # before step N+1 is decided.
        assert during == [0, 1, 2]

    def test_observer_failure_does_not_abort_the_run(self):
        def explode(step):
            raise RuntimeError("viewer blew up")

        executor = FakeExecutor(elements())
        result = AgentLoop(
            executor, ScriptedDecider([fill(0, "Ada")]), on_step=explode
        ).run()
        assert result.performed_count == 1, "a viewer must not break the agent"

    def test_failures_are_reported_too(self):
        executor = FakeExecutor(elements(), framework_controlled={"Full name"})
        seen: list[Step] = []
        AgentLoop(executor, ScriptedDecider([fill(0, "Ada")]), on_step=seen.append).run()
        assert seen[0].performed
        assert not seen[0].verified


class TestRunRecord:
    def test_collects_steps(self, runs):
        run = runs.start("Apply to Northwind")
        executor = FakeExecutor(elements())
        AgentLoop(
            executor, ScriptedDecider([fill(0, "Ada")]), on_step=run.record
        ).run()
        assert len(run.steps) == 1

    def test_running_until_finished(self, runs):
        from haru.execution.guard import StopReason

        run = runs.start("x")
        assert run.is_running
        run.finish(StopReason.COMPLETED)
        assert not run.is_running
        assert run.reason is StopReason.COMPLETED

    def test_counts_verified_and_problems(self, runs):
        run = runs.start("x")
        executor = FakeExecutor(elements(), framework_controlled={"Full name"})
        AgentLoop(
            executor,
            ScriptedDecider([fill(0, "Ada"), fill(1, "e@x.com")]),
            on_step=run.record,
        ).run()
        assert run.verified_count == 1
        assert run.has_problems

    def test_events_are_serialisable(self, runs):
        run = runs.start("x")
        AgentLoop(
            FakeExecutor(elements()), ScriptedDecider([fill(0, "Ada")]), on_step=run.record
        ).run()
        events = run.as_events()
        assert json.dumps(events)
        assert events[0]["verified"] is True

    def test_events_since_offset(self, runs):
        run = runs.start("x")
        AgentLoop(
            FakeExecutor(elements()),
            ScriptedDecider([fill(0, "a"), fill(1, "b")]),
            on_step=run.record,
        ).run()
        assert len(run.as_events(since=1)) == 1
        assert run.as_events(since=1)[0]["index"] == 1

    def test_wait_wakes_on_a_new_step(self, runs):
        run = runs.start("x")
        woke = threading.Event()

        def watcher():
            if run.wait_for_change(timeout=5.0):
                woke.set()

        thread = threading.Thread(target=watcher)
        thread.start()
        AgentLoop(
            FakeExecutor(elements()), ScriptedDecider([fill(0, "Ada")]), on_step=run.record
        ).run()
        thread.join(timeout=5)
        assert woke.is_set()


class TestRunManager:
    def test_active_and_recent(self, runs):
        from haru.execution.guard import StopReason

        a = runs.start("a")
        b = runs.start("b")
        b.finish(StopReason.COMPLETED)
        assert [r.id for r in runs.active()] == [a.id]
        assert len(runs.recent()) == 2

    def test_unknown_run(self, runs):
        assert runs.get("nope") is None


class TestRunPage:
    def test_renders_steps_server_side(self, client, runs):
        run = runs.start("Apply to Northwind")
        AgentLoop(
            FakeExecutor(elements()), ScriptedDecider([fill(0, "Ada Lovelace")]),
            on_step=run.record,
        ).run()

        body = client.get(f"/run/{run.id}").text
        assert "Apply to Northwind" in body
        assert "Ada Lovelace" in body
        assert "verified" in body

    def test_timeline_readable_without_scripting(self, client, runs):
        """The table is server-rendered; the stream only appends."""
        run = runs.start("x")
        AgentLoop(
            FakeExecutor(elements()), ScriptedDecider([fill(0, "Ada")]), on_step=run.record
        ).run()
        body = client.get(f"/run/{run.id}").text
        table_part = body.split("<script>")[0]
        assert "Ada" in table_part

    def test_unverified_step_is_shown_as_such(self, client, runs):
        run = runs.start("x")
        AgentLoop(
            FakeExecutor(elements(), framework_controlled={"Full name"}),
            ScriptedDecider([fill(0, "Ada")]),
            on_step=run.record,
        ).run()
        assert "unverified" in client.get(f"/run/{run.id}").text

    def test_missing_run(self, client):
        assert "No run here" in client.get("/run/nope").text

    def test_script_is_inline_not_fetched(self, client, runs):
        run = runs.start("x")
        body = client.get(f"/run/{run.id}").text
        assert "<script>" in body
        assert "src=" not in body.split("<script>")[1].split("</script>")[0]


class TestStream:
    def test_sse_framing(self):
        frame = sse("step", {"index": 0})
        assert frame.startswith("event: step\n")
        assert '"index": 0' in frame
        assert frame.endswith("\n\n")

    def test_finished_run_streams_and_closes(self, runs):
        from haru.execution.guard import StopReason

        run = runs.start("x")
        AgentLoop(
            FakeExecutor(elements()), ScriptedDecider([fill(0, "Ada")]), on_step=run.record
        ).run()
        run.finish(StopReason.COMPLETED)

        frames = list(stream(run))
        assert any("event: summary" in f for f in frames)
        assert any("event: step" in f for f in frames)
        assert frames[-1].startswith("event: done")

    def test_stream_endpoint_is_event_stream(self, client, runs):
        from haru.execution.guard import StopReason

        run = runs.start("x")
        run.finish(StopReason.COMPLETED)
        with client.stream("GET", f"/run/{run.id}/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]

    def test_stream_404(self, client):
        assert client.get("/run/nope/stream").status_code == 404


class TestCli:
    def test_parser_builds(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--port", "9000"])
        assert args.port == 9000
        assert args.host == "127.0.0.1", "loopback by default"

    def test_no_command_prints_help(self, capsys):
        assert main([]) == 1
        assert "usage" in capsys.readouterr().out

    def test_brain_flag_works_on_either_side_of_the_subcommand(self, tmp_path, capsys):
        """`haru status --brain X` is what people type; both must work."""
        from haru.brain.store import BrainStore

        path = tmp_path / "brain.sqlite"
        BrainStore(path).close()

        assert main(["status", "--brain", str(path)]) == 0
        assert str(path) in capsys.readouterr().out

        assert main(["--brain", str(path), "status"]) == 0
        assert str(path) in capsys.readouterr().out

    def test_status_on_missing_brain(self, tmp_path, capsys):
        code = main(["--brain", str(tmp_path / "none.sqlite"), "status"])
        assert code == 1
        assert "No Brain" in capsys.readouterr().out

    def test_status_reports_an_empty_boundary(self, tmp_path, capsys):
        from haru.brain.store import BrainStore

        path = tmp_path / "brain.sqlite"
        BrainStore(path).close()
        assert main(["--brain", str(path), "status"]) == 0
        assert "fact boundary is empty" in capsys.readouterr().out

    def test_export(self, tmp_path, capsys):
        from haru.brain.models import Project
        from haru.brain.provenance import Provenance
        from haru.brain.store import BrainStore

        path = tmp_path / "brain.sqlite"
        store = BrainStore(path)
        store.put(Project(name="Haru", provenance=Provenance.entered()))
        store.close()

        out = tmp_path / "export.json"
        assert main(["--brain", str(path), "export", str(out)]) == 0
        assert "Haru" in out.read_text(encoding="utf-8")

    def test_export_redacted(self, tmp_path):
        from haru.brain.models import Compensation
        from haru.brain.store import BrainStore

        path = tmp_path / "brain.sqlite"
        store = BrainStore(path)
        store.put_singleton(Compensation(current_salary=70000))
        store.close()

        out = tmp_path / "export.json"
        main(["--brain", str(path), "export", str(out), "--redact"])
        assert "70000" not in out.read_text(encoding="utf-8")
