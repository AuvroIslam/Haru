"""Playwright executor tests against real Chromium (PRD §12.4).

These run a browser. If one is not installed the module skips rather than
failing, so the suite stays usable on machines without the download.

The centrepiece is :class:`TestNativeSetter`, which reproduces the
React-controlled-input bug and proves the fix. Everything else in the execution
layer can be tested against a fake; this one cannot, because the bug lives in
the interaction between a real DOM and a framework's value tracker.
"""

import pytest

from haru.execution.actions import Action, ActionType
from haru.execution.loop import AgentLoop, ScriptedDecider, verify
from haru.execution.page import ElementRole
from haru.validation.seam import reset_validator, set_validator
from haru.validation.types import Result, ValidationMode

playwright_api = pytest.importorskip("playwright.sync_api")

from haru.execution.browser import NATIVE_SETTER_JS, PlaywrightExecutor  # noqa: E402


class RealValidator:
    def validate(self, artifact, boundary, mode=ValidationMode.NORMAL):
        return Result(artifact=artifact, mode=mode)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            instance = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium unavailable: {exc}")
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture(autouse=True)
def _clean_validator():
    reset_validator()
    yield
    reset_validator()


# A minimal but faithful model of a React controlled input: component state is
# updated only by the events React listens for, and a re-render writes state
# back over whatever is in the DOM.
CONTROLLED_INPUT = """
<label for="name">Full name</label>
<input id="name">
<script>
  const el = document.getElementById('name');
  window.componentState = '';
  el.addEventListener('input', e => { window.componentState = e.target.value; });
  window.rerender = () => { el.value = window.componentState; };
</script>
"""

APPLICATION_FORM = """
<h1>Apply</h1>
<form>
  <label for="name">Full name</label><input id="name" required>
  <label for="email">Email</label><input id="email" type="email" required>
  <label for="country">Country</label>
  <select id="country"><option value="">--</option><option value="UK">UK</option><option value="US">US</option></select>
  <label for="agree">Agree to terms</label><input id="agree" type="checkbox">
  <textarea id="why" placeholder="Why do you want this role?"></textarea>
  <input id="secret" type="hidden" value="xyz">
  <button id="send" type="button" onclick="document.body.innerHTML='<h1>Application submitted</h1>'">Send</button>
</form>
"""


class TestNativeSetter:
    """The bug: a filled-looking field that submits empty."""

    def test_naive_assignment_is_lost_on_rerender(self, page):
        page.set_content(CONTROLLED_INPUT)
        page.eval_on_selector("#name", "el => { el.value = 'Ada Lovelace'; }")
        assert page.input_value("#name") == "Ada Lovelace", "DOM looks filled"

        page.evaluate("window.rerender()")
        assert page.input_value("#name") == "", "…but the component never saw it"
        assert page.evaluate("window.componentState") == ""

    def test_native_setter_survives_rerender(self, page):
        page.set_content(CONTROLLED_INPUT)
        page.eval_on_selector("#name", NATIVE_SETTER_JS, "Ada Lovelace")

        assert page.evaluate("window.componentState") == "Ada Lovelace"
        page.evaluate("window.rerender()")
        assert page.input_value("#name") == "Ada Lovelace"

    def test_executor_fill_uses_the_native_setter(self, page):
        page.set_content(CONTROLLED_INPUT)
        executor = PlaywrightExecutor(page)
        snap = executor.snapshot()
        field = snap.by_label("Full name")

        executor.perform(
            Action(action_type=ActionType.FILL, target=field.index, value="Ada"), field
        )

        assert page.evaluate("window.componentState") == "Ada"
        page.evaluate("window.rerender()")
        assert page.input_value("#name") == "Ada"

    def test_verification_would_have_caught_the_naive_path(self, page):
        """Even if the setter regressed, post-action verification catches it."""
        page.set_content(CONTROLLED_INPUT)
        executor = PlaywrightExecutor(page)
        before = executor.snapshot()
        field = before.by_label("Full name")

        page.eval_on_selector("#name", "el => { el.value = 'Ada'; }")
        page.evaluate("window.rerender()")

        action = Action(action_type=ActionType.FILL, target=field.index, value="Ada")
        ok, why = verify(action, before, executor.snapshot())
        assert not ok
        assert "framework-controlled" in why


class TestScanning:
    def test_finds_interactive_elements(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        labels = {e.label for e in snap.elements}
        assert "Full name" in labels
        assert "Email" in labels

    def test_assigns_sequential_indices(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        assert [e.index for e in snap.elements] == list(range(len(snap.elements)))

    def test_reads_roles(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        assert snap.by_label("Full name").role is ElementRole.TEXTBOX
        assert snap.by_label("Country").role is ElementRole.SELECT
        assert snap.by_label("Agree to terms").role is ElementRole.CHECKBOX

    def test_label_association_via_for_attribute(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        assert snap.by_label("Email") is not None

    def test_labels_do_not_shadow_their_control(self, page):
        """A <label for> must name the input, not become a target itself."""
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        named = [e for e in snap.elements if e.label == "Full name"]
        assert len(named) == 1
        assert named[0].tag == "input"

    def test_placeholder_used_when_no_label(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        assert snap.by_label("Why do you want this role?") is not None

    def test_hidden_inputs_are_excluded(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        assert all(e.selector != "#secret" for e in snap.elements)

    def test_display_none_is_excluded(self, page):
        page.set_content('<input id="a"><input id="b" style="display:none">')
        snap = PlaywrightExecutor(page).snapshot()
        assert len(snap.elements) == 1

    def test_zero_size_elements_are_kept(self, page):
        """Invisible overlays are real click targets — size is not a filter."""
        page.set_content(
            '<button id="ghost" style="width:0;height:0;padding:0;border:0">x</button>'
        )
        snap = PlaywrightExecutor(page).snapshot()
        assert len(snap.elements) == 1
        assert snap.elements[0].width == 0

    def test_reads_select_options(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        assert set(snap.by_label("Country").options) == {"", "UK", "US"}

    def test_required_flag(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        assert snap.by_label("Full name").required
        assert not snap.by_label("Country").required

    def test_unfilled_required_reported(self, page):
        page.set_content(APPLICATION_FORM)
        snap = PlaywrightExecutor(page).snapshot()
        assert {e.label for e in snap.unfilled_required} == {"Full name", "Email"}

    def test_stable_key_survives_a_rescan(self, page):
        page.set_content(APPLICATION_FORM)
        executor = PlaywrightExecutor(page)
        first = executor.snapshot().by_label("Email").stable_key
        assert executor.snapshot().by_label("Email").stable_key == first


class TestActions:
    def test_select_option(self, page):
        page.set_content(APPLICATION_FORM)
        executor = PlaywrightExecutor(page)
        snap = executor.snapshot()
        target = snap.by_label("Country")
        executor.perform(
            Action(action_type=ActionType.SELECT, target=target.index, value="UK"), target
        )
        assert page.input_value("#country") == "UK"

    def test_checkbox(self, page):
        page.set_content(APPLICATION_FORM)
        executor = PlaywrightExecutor(page)
        snap = executor.snapshot()
        box = snap.by_label("Agree to terms")
        executor.perform(
            Action(action_type=ActionType.CHECK, target=box.index, value="true"), box
        )
        assert page.is_checked("#agree")

    def test_textarea_uses_native_setter_path(self, page):
        page.set_content(APPLICATION_FORM)
        executor = PlaywrightExecutor(page)
        snap = executor.snapshot()
        area = snap.by_label("Why do you want this role?")
        assert area.needs_native_setter
        executor.perform(
            Action(action_type=ActionType.FILL, target=area.index, value="Because."), area
        )
        assert page.input_value("#why") == "Because."

    def test_missing_target_raises(self, page):
        from haru.execution.executor import TargetNotFound
        from haru.execution.page import Element

        page.set_content(APPLICATION_FORM)
        executor = PlaywrightExecutor(page)
        ghost = Element(index=99, role=ElementRole.TEXTBOX, selector="#nope", tag="input")
        with pytest.raises(TargetNotFound):
            executor.perform(
                Action(action_type=ActionType.FILL, target=99, value="x"), ghost
            )


class TestLoopAgainstRealBrowser:
    def test_fills_a_form_with_every_step_verified(self, page):
        page.set_content(APPLICATION_FORM)
        executor = PlaywrightExecutor(page)
        snap = executor.snapshot()

        name = snap.by_label("Full name").index
        email = snap.by_label("Email").index
        country = snap.by_label("Country").index

        result = AgentLoop(
            executor,
            ScriptedDecider(
                [
                    Action(action_type=ActionType.FILL, target=name, value="Ada Lovelace"),
                    Action(action_type=ActionType.FILL, target=email, value="ada@example.com"),
                    Action(action_type=ActionType.SELECT, target=country, value="UK"),
                ]
            ),
        ).run()

        assert result.performed_count == 3
        assert all(s.verified for s in result.steps), [s.note for s in result.steps]
        assert page.input_value("#name") == "Ada Lovelace"
        assert page.input_value("#country") == "UK"

    def test_submit_requires_approval_and_confirms(self, page):
        set_validator(RealValidator())
        page.set_content(APPLICATION_FORM)
        executor = PlaywrightExecutor(page)
        send = executor.snapshot().by_label("Send").index

        result = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=send)]),
            approval=lambda a, s: True,
        ).run()

        assert result.steps[-1].verified
        # Assert on rendered text, not page source — the source contains the
        # word "submitted" inside the button's onclick handler either way.
        assert page.inner_text("h1") == "Application submitted"

    def test_submit_refused_while_validation_stubbed(self, page):
        from haru.execution.guard import StopReason

        page.set_content(APPLICATION_FORM)
        executor = PlaywrightExecutor(page)
        send = executor.snapshot().by_label("Send").index

        result = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=send)]),
            approval=lambda a, s: True,
        ).run()

        assert result.reason is StopReason.BLOCKED
        assert page.inner_text("h1") == "Apply", "the form must be untouched"
