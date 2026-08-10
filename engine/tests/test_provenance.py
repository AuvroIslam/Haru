"""Tests for provenance primitives (PRD §6.1)."""

import pytest
from pydantic import ValidationError

from haru.brain.provenance import (
    DEFAULT_CONFIDENCE,
    DIRECT_SOURCES,
    Attested,
    Provenance,
    Source,
)


class TestProvenance:
    def test_entered_is_confirmed_immediately(self):
        p = Provenance.entered("typed in setup")
        assert p.confirmed
        assert p.confirmed_at is not None
        assert p.confidence == 1.0
        assert p.source in DIRECT_SOURCES

    def test_import_is_not_confirmed(self):
        p = Provenance.create(Source.CV_IMPORT, detail="resume.pdf")
        assert not p.confirmed
        assert p.confirmed_at is None

    def test_confidence_defaults_from_source(self):
        for source, expected in DEFAULT_CONFIDENCE.items():
            assert Provenance.create(source).confidence == expected

    def test_explicit_confidence_overrides_default(self):
        p = Provenance.create(Source.CV_IMPORT, confidence=0.95)
        assert p.confidence == 0.95

    def test_confidence_must_be_a_probability(self):
        with pytest.raises(ValidationError):
            Provenance(source=Source.USER_ENTERED, confidence=1.5)
        with pytest.raises(ValidationError):
            Provenance(source=Source.USER_ENTERED, confidence=-0.1)

    def test_confirmed_without_timestamp_is_rejected(self):
        with pytest.raises(ValidationError, match="confirmed_at"):
            Provenance(source=Source.CV_IMPORT, confidence=0.6, confirmed=True)

    def test_timestamp_without_confirmation_is_rejected(self):
        from haru.brain.provenance import utcnow

        with pytest.raises(ValidationError, match="unconfirmed"):
            Provenance(
                source=Source.CV_IMPORT,
                confidence=0.6,
                confirmed=False,
                confirmed_at=utcnow(),
            )

    def test_confirm_produces_confirmed_copy(self):
        p = Provenance.create(Source.GITHUB_IMPORT)
        c = p.confirm()
        assert not p.confirmed, "original must not mutate"
        assert c.confirmed
        assert c.confirmed_at is not None
        assert c.source == p.source

    def test_confirm_is_idempotent(self):
        p = Provenance.entered()
        assert p.confirm() is p

    def test_provenance_is_frozen(self):
        p = Provenance.entered()
        with pytest.raises(ValidationError):
            p.confidence = 0.1

    def test_recorded_at_is_timezone_aware(self):
        # Naive datetimes compare wrongly across imports; guard against regression.
        assert Provenance.entered().recorded_at.tzinfo is not None


class TestToday:
    """Deadlines and expiry are local calendar facts, not UTC ones."""

    def test_today_is_the_local_date(self):
        from datetime import datetime

        from haru.brain.provenance import today

        assert today() == datetime.now().date()

    def test_today_may_differ_from_the_utc_date(self):
        """The bug this guards: mixing the two puts expiry out by a day.

        East of Greenwich after midnight local, ``utcnow().date()`` is still
        yesterday — so a deadline that has passed still looks open.
        """
        from haru.brain.provenance import today, utcnow

        difference = abs((today() - utcnow().date()).days)
        assert difference <= 1, "sanity: the two can differ by at most a day"


class TestAttested:
    def test_entered_value_is_confirmed(self):
        a = Attested.entered("Ada Lovelace")
        assert a.value == "Ada Lovelace"
        assert a.is_confirmed

    def test_imported_value_needs_review(self):
        a = Attested.imported("Ada Lovelace", Source.CV_IMPORT, detail="cv.pdf")
        assert not a.is_confirmed
        assert a.provenance.detail == "cv.pdf"

    def test_confirm_does_not_mutate_original(self):
        a = Attested.imported(42, Source.DOCUMENT_EXTRACTION)
        c = a.confirm()
        assert not a.is_confirmed
        assert c.is_confirmed
        assert c.value == 42

    def test_carries_non_string_values(self):
        a = Attested.entered(["python", "rust"])
        assert a.value == ["python", "rust"]
