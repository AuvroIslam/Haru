"""Tests for form-field mapping (PRD §4.2, §8.1, §16.3)."""

from datetime import date

import pytest

from haru.adapters.fields import (
    HIGH_STAKES_THRESHOLD,
    STANDARD_THRESHOLD,
    BrainView,
    FieldMapper,
)
from haru.brain.models import (
    Availability,
    Compensation,
    Identity,
    Link,
    StandardAnswers,
    VoluntaryDisclosure,
    WorkAuthorization,
)
from haru.brain.provenance import Attested
from haru.brain.store import BrainStore


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    s.put_singleton(
        Identity(
            legal_name=Attested.entered("Ada Lovelace"),
            emails=[Attested.entered("ada@example.com")],
            phones=[Attested.entered("+44 20 7946 0000")],
            street=Attested.entered("12 Analytical Way"),
            city=Attested.entered("London"),
            country=Attested.entered("United Kingdom"),
            postal_code=Attested.entered("EC1A 1BB"),
            links=[
                Link(label="LinkedIn", url="https://linkedin.com/in/ada"),
                Link(label="GitHub", url="https://github.com/ada"),
                Link(label="Site", url="https://ada.example.com"),
            ],
        )
    )
    s.put_singleton(
        WorkAuthorization(legally_authorized_in=["GB"], requires_sponsorship=False)
    )
    s.put_singleton(Availability(earliest_start_date=date(2026, 9, 1)))
    s.put_singleton(Compensation(expectation=90000, current_salary=70000))
    s.put_singleton(
        StandardAnswers(
            age_18_or_over=True,
            background_check_consent=True,
            previously_employed_here=False,
            how_did_you_hear="Online job board",
        )
    )
    yield s
    s.close()


@pytest.fixture
def mapper(store):
    return FieldMapper.from_store(store)


class TestIdentityFields:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Full name", "Ada Lovelace"),
            ("Your Name", "Ada Lovelace"),
            ("Legal Name", "Ada Lovelace"),
            ("Email Address", "ada@example.com"),
            ("Phone", "+44 20 7946 0000"),
            ("City", "London"),
            ("Country", "United Kingdom"),
            ("Postal Code", "EC1A 1BB"),
        ],
    )
    def test_maps_common_labels(self, mapper, label, expected):
        match = mapper.match(label)
        assert match.value == expected
        assert match.is_auto_fillable()

    def test_splits_name_parts(self, mapper):
        assert mapper.match("First Name").value == "Ada"
        assert mapper.match("Last Name").value == "Lovelace"

    def test_links_are_routed_by_host(self, mapper):
        assert "linkedin.com" in mapper.match("LinkedIn URL").value
        assert "github.com" in mapper.match("GitHub profile").value
        assert mapper.match("Portfolio").value == "https://ada.example.com"

    def test_label_punctuation_and_case_tolerated(self, mapper):
        assert mapper.match("E-MAIL ADDRESS:").value == "ada@example.com"
        assert mapper.match("  full name *  ").value == "Ada Lovelace"


class TestWorkEligibility:
    def test_authorization(self, mapper):
        match = mapper.match("Are you legally authorized to work in the UK?")
        assert match.value == "Yes"
        assert match.is_auto_fillable()

    def test_sponsorship(self, mapper):
        match = mapper.match(
            "Will you now or in the future require visa sponsorship?"
        )
        assert match.value == "No"

    def test_start_date(self, mapper):
        assert mapper.match("Earliest start date").value == "2026-09-01"


class TestSensitiveFields:
    """PRD §16.3 — protected characteristics are never auto-filled."""

    @pytest.mark.parametrize(
        "label", ["Gender", "Race / Ethnicity", "Veteran status", "Disability status"]
    )
    def test_disclosures_are_always_asked(self, mapper, label):
        match = mapper.match(label)
        assert match.sensitive
        assert match.always_ask
        assert not match.is_auto_fillable(), "must never be filled silently"

    def test_disclosures_default_to_declining(self, mapper):
        assert mapper.match("Gender").value == "decline_to_self_identify"

    def test_current_salary_is_never_proposed(self, mapper):
        match = mapper.match("Current salary")
        assert match.value is None
        assert match.always_ask
        assert "unlawful" in match.note

    def test_salary_expectation_is_proposed(self, mapper):
        match = mapper.match("Salary expectation")
        assert match.value == "90000"
        assert not match.sensitive

    def test_current_salary_beats_salary_expectation_pattern(self, mapper):
        # Both rules mention "salary"; the longer, more specific pattern wins.
        assert mapper.match("Current salary").canonical == "current_salary"
        assert mapper.match("Salary expectation").canonical == "salary_expectation"

    def test_criminal_record_is_left_to_the_user(self, mapper):
        match = mapper.match("Have you ever been convicted of a felony?")
        assert match.value is None
        assert match.always_ask


class TestStandardAnswers:
    def test_yes_no_conversion(self, mapper):
        assert mapper.match("Are you over 18?").value == "Yes"
        assert mapper.match("Have you previously worked here?").value == "No"

    def test_how_heard(self, mapper):
        assert mapper.match("How did you hear about us?").value == "Online job board"


class TestUnknownAndMissing:
    def test_unrecognised_label(self, mapper):
        match = mapper.match("What is your favourite colour?")
        assert match.is_unknown
        assert match.confidence == 0.0
        assert not match.is_auto_fillable()

    def test_empty_label(self, mapper):
        assert mapper.match("   ").is_unknown

    def test_known_label_with_no_data_is_not_fillable(self, tmp_path):
        empty = BrainStore(tmp_path / "empty.sqlite")
        try:
            match = FieldMapper.from_store(empty).match("Full name")
            assert match.is_unknown
            assert match.confidence == 0.0
            assert not match.is_auto_fillable()
        finally:
            empty.close()

    def test_missing_link_type(self, tmp_path):
        s = BrainStore(tmp_path / "b.sqlite")
        try:
            s.put_singleton(Identity(legal_name=Attested.entered("Ada")))
            assert FieldMapper.from_store(s).match("GitHub").is_unknown
        finally:
            s.close()


class TestThresholds:
    def test_high_stakes_is_stricter(self, mapper):
        """PRD §8.3 — government forms demand near-certainty."""
        match = mapper.match("Please provide your email so we can reply")
        assert match.is_auto_fillable(STANDARD_THRESHOLD)
        assert not match.is_auto_fillable(HIGH_STAKES_THRESHOLD)

    def test_email_beats_address_in_a_compound_label(self, mapper):
        """Regression: 'Email Address' once resolved to the street address."""
        for label in ["Email Address", "E-MAIL ADDRESS:", "e-mail address"]:
            match = mapper.match(label)
            assert match.canonical == "email", label
            assert match.value == "ada@example.com"

    def test_street_address_still_wins_for_addresses(self, mapper):
        assert mapper.match("Street Address").canonical == "address"
        assert mapper.match("Address line 1").canonical == "address"

    def test_exact_label_scores_above_substring(self, mapper):
        exact = mapper.match("email")
        embedded = mapper.match("Please provide your email so we can reply")
        assert exact.confidence > embedded.confidence

    def test_never_guesses_below_threshold(self, mapper):
        for label in ["Gender", "Current salary", "Favourite colour"]:
            assert not mapper.match(label).is_auto_fillable()


class TestBatch:
    def test_match_all_preserves_order(self, mapper):
        labels = ["Full name", "Email", "Gender"]
        matches = mapper.match_all(labels)
        assert [m.label for m in matches] == labels

    def test_separates_fillable_from_ask(self, mapper):
        matches = mapper.match_all(
            ["Full name", "Email", "Gender", "Favourite colour"]
        )
        auto = [m.canonical for m in matches if m.is_auto_fillable()]
        ask = [m.canonical for m in matches if not m.is_auto_fillable()]
        assert set(auto) == {"full_name", "email"}
        assert set(ask) == {"gender", "unknown"}


class TestBrainView:
    def test_loads_all_blocks(self, store):
        view = BrainView.load(store)
        assert view.identity is not None
        assert view.work_authorization is not None
        assert view.compensation is not None

    def test_tolerates_empty_brain(self, tmp_path):
        empty = BrainStore(tmp_path / "e.sqlite")
        try:
            view = BrainView.load(empty)
            assert view.identity is None
            assert FieldMapper(view).match("Full name").is_unknown
        finally:
            empty.close()
