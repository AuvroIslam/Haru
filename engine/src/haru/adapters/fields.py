"""Mapping form fields to what the Brain knows (PRD §4.2, §8.1).

A form asks "Full name"; the Brain has ``identity.legal_name``. This module is
the join, and it returns a *confidence* with every answer rather than a bare
value, because the interesting cases are the uncertain ones.

Three rules that are easy to get wrong and expensive to get wrong:

* **Below the threshold, ask — do not guess.** A plausible wrong answer on an
  application is worse than an empty field, because the user never sees it.
* **Protected characteristics are never auto-filled.** EEO questions resolve to
  "decline to self-identify" and are always surfaced (PRD §16.3).
* **Salary history is left blank.** Employers ask; it is prohibited in many
  jurisdictions, and volunteering it only ever costs the user money.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from datetime import date

from haru.brain.models import (
    DEFAULT_PROFILE_ID,
    Availability,
    Compensation,
    Identity,
    StandardAnswers,
    VoluntaryDisclosure,
    WorkAuthorization,
)
from haru.brain.store import BrainStore

#: Auto-fill at or above this. Below it, the user is asked (PRD §8.3).
STANDARD_THRESHOLD = 0.8
#: Government and institutional forms demand near-certainty.
HIGH_STAKES_THRESHOLD = 0.95


@dataclass(frozen=True)
class FieldMatch:
    """A proposed answer for one form field."""

    label: str
    canonical: str
    value: str | None
    confidence: float
    source: str
    sensitive: bool = False
    #: True when the user must decide rather than the agent proposing.
    always_ask: bool = False
    note: str = ""

    def is_auto_fillable(self, threshold: float = STANDARD_THRESHOLD) -> bool:
        if self.always_ask or self.value is None:
            return False
        return self.confidence >= threshold

    @property
    def is_unknown(self) -> bool:
        return self.value is None


@dataclass
class BrainView:
    """The singleton blocks a mapper needs, loaded once."""

    identity: Identity | None = None
    work_authorization: WorkAuthorization | None = None
    availability: Availability | None = None
    compensation: Compensation | None = None
    disclosure: VoluntaryDisclosure | None = None
    standard: StandardAnswers | None = None

    @classmethod
    def load(
        cls, store: BrainStore, *, profile_id: str = DEFAULT_PROFILE_ID
    ) -> BrainView:
        return cls(
            identity=store.get_singleton(Identity, profile_id=profile_id),
            work_authorization=store.get_singleton(WorkAuthorization, profile_id=profile_id),
            availability=store.get_singleton(Availability, profile_id=profile_id),
            compensation=store.get_singleton(Compensation, profile_id=profile_id),
            disclosure=store.get_singleton(VoluntaryDisclosure, profile_id=profile_id),
            standard=store.get_singleton(StandardAnswers, profile_id=profile_id),
        )


@dataclass(frozen=True)
class Rule:
    """One label pattern and where its answer comes from."""

    canonical: str
    patterns: tuple[str, ...]
    resolver: str
    sensitive: bool = False
    always_ask: bool = False
    note: str = ""
    #: Confidence when the label matches exactly one pattern strongly.
    confidence: float = 0.95


def _attested(value) -> str | None:
    return str(value.value) if value is not None else None


def _yes_no(value: bool | None) -> str | None:
    if value is None:
        return None
    return "Yes" if value else "No"


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


RULES: tuple[Rule, ...] = (
    Rule("full_name", ("full name", "your name", "legal name", "name"), "full_name"),
    Rule("first_name", ("first name", "given name", "forename"), "first_name"),
    Rule("last_name", ("last name", "surname", "family name"), "last_name"),
    Rule("preferred_name", ("preferred name", "nickname", "goes by"), "preferred_name"),
    Rule("email", ("email", "e-mail", "email address"), "email"),
    Rule("phone", ("phone", "telephone", "mobile", "contact number"), "phone"),
    Rule("address", ("street address", "address line", "address"), "address"),
    Rule("city", ("city", "town"), "city"),
    Rule("region", ("state", "province", "region", "county"), "region"),
    Rule("country", ("country",), "country"),
    Rule("postal_code", ("postal code", "zip code", "zip", "postcode"), "postal_code"),
    Rule("linkedin", ("linkedin",), "linkedin"),
    Rule("github", ("github",), "github"),
    Rule("portfolio", ("portfolio", "website", "personal site"), "portfolio"),
    Rule(
        "work_authorization",
        ("legally authorized", "authorised to work", "authorized to work",
         "right to work", "eligible to work"),
        "work_authorized",
    ),
    Rule(
        "sponsorship",
        ("require sponsorship", "need sponsorship", "visa sponsorship",
         "will you now or in the future require"),
        "sponsorship",
    ),
    Rule("start_date", ("start date", "available from", "earliest start", "notice period"), "start_date"),
    Rule(
        "salary_expectation",
        ("salary expectation", "expected salary", "desired salary",
         "compensation expectation"),
        "salary_expectation",
        confidence=0.85,
    ),
    Rule(
        "current_salary",
        ("current salary", "salary history", "present salary"),
        "current_salary",
        sensitive=True,
        always_ask=True,
        note="often unlawful to ask; left blank unless you choose otherwise",
    ),
    Rule("gender", ("gender", "sex"), "gender", sensitive=True, always_ask=True,
         note="voluntary disclosure — declines by default"),
    Rule("race", ("race", "ethnicity", "ethnic"), "race", sensitive=True, always_ask=True,
         note="voluntary disclosure — declines by default"),
    Rule("veteran", ("veteran", "military service"), "veteran", sensitive=True, always_ask=True,
         note="voluntary disclosure — declines by default"),
    Rule("disability", ("disability", "disabled"), "disability", sensitive=True, always_ask=True,
         note="voluntary disclosure — declines by default"),
    Rule("age_18", ("18 years", "over 18", "at least 18", "age 18"), "age_18"),
    Rule("background_check", ("background check", "background screening"), "background_check"),
    Rule("criminal_record", ("criminal", "convicted", "felony"), "criminal_record",
         sensitive=True, always_ask=True, note="answer this yourself"),
    Rule("previously_employed", ("previously worked", "former employee",
                                 "worked here before"), "previously_employed"),
    Rule("how_heard", ("how did you hear", "how you heard", "referral source"), "how_heard",
         confidence=0.85),
)


class FieldMapper:
    """Proposes answers for form fields from the Brain."""

    def __init__(self, view: BrainView) -> None:
        self.view = view

    @classmethod
    def from_store(
        cls, store: BrainStore, *, profile_id: str = DEFAULT_PROFILE_ID
    ) -> FieldMapper:
        return cls(BrainView.load(store, profile_id=profile_id))

    def match(self, label: str) -> FieldMatch:
        """Find the best rule for a label and resolve its value."""
        rule, strength = self._best_rule(label)
        if rule is None:
            return FieldMatch(
                label=label,
                canonical="unknown",
                value=None,
                confidence=0.0,
                source="no matching field",
                note="Haru does not recognise this question",
            )

        value = getattr(self, f"_resolve_{rule.resolver}")()
        confidence = rule.confidence * strength if value is not None else 0.0
        return FieldMatch(
            label=label,
            canonical=rule.canonical,
            value=value,
            confidence=round(confidence, 3),
            source=rule.resolver,
            sensitive=rule.sensitive,
            always_ask=rule.always_ask,
            note=rule.note,
        )

    def match_all(self, labels: list[str]) -> list[FieldMatch]:
        return [self.match(label) for label in labels]

    # ── rule selection ───────────────────────────────────────────────────

    @staticmethod
    def _clean(label: str) -> str:
        """Normalise a label for matching.

        Hyphens and apostrophes are *removed* rather than spaced, so "E-mail"
        becomes "email" and matches the email rule. Everything else becomes a
        space.
        """
        lowered = re.sub(r"[-']", "", label.lower())
        spaced = re.sub(r"[^a-z0-9 ]+", " ", lowered)
        return re.sub(r"\s+", " ", spaced).strip()

    def _best_rule(self, label: str) -> tuple[Rule | None, float]:
        """Pick the rule whose pattern fits best.

        **Earliest match wins, then longest.** Position matters more than length
        because the leading words name the subject: "Email Address" contains
        both "email" and "address", and answering it with a street address is a
        plausible-looking wrong answer the user would never see. Length still
        breaks ties, so "street address" beats "address" and "current salary"
        beats a bare "salary" overlap.
        """
        cleaned = self._clean(label)
        if not cleaned:
            return None, 0.0

        best: tuple[Rule, float, int, int] | None = None
        for rule in RULES:
            for pattern in rule.patterns:
                position = cleaned.find(pattern)
                if position < 0:
                    continue
                # Exact label match is certain; a substring is slightly less so.
                strength = 1.0 if cleaned == pattern else 0.9
                candidate = (rule, strength, position, len(pattern))
                if best is None or (position, -len(pattern)) < (best[2], -best[3]):
                    best = candidate
        if best is None:
            return None, 0.0
        return best[0], best[1]

    # ── resolvers ────────────────────────────────────────────────────────

    def _resolve_full_name(self) -> str | None:
        ident = self.view.identity
        if ident is None:
            return None
        return _attested(ident.legal_name) or _attested(ident.preferred_name)

    def _resolve_first_name(self) -> str | None:
        full = self._resolve_full_name()
        return full.split()[0] if full else None

    def _resolve_last_name(self) -> str | None:
        full = self._resolve_full_name()
        parts = full.split() if full else []
        return parts[-1] if len(parts) > 1 else None

    def _resolve_preferred_name(self) -> str | None:
        ident = self.view.identity
        return _attested(ident.preferred_name) if ident else None

    def _resolve_email(self) -> str | None:
        ident = self.view.identity
        return _attested(ident.emails[0]) if ident and ident.emails else None

    def _resolve_phone(self) -> str | None:
        ident = self.view.identity
        return _attested(ident.phones[0]) if ident and ident.phones else None

    def _resolve_address(self) -> str | None:
        ident = self.view.identity
        return _attested(ident.street) if ident else None

    def _resolve_city(self) -> str | None:
        ident = self.view.identity
        return _attested(ident.city) if ident else None

    def _resolve_region(self) -> str | None:
        ident = self.view.identity
        return _attested(ident.region) if ident else None

    def _resolve_country(self) -> str | None:
        ident = self.view.identity
        return _attested(ident.country) if ident else None

    def _resolve_postal_code(self) -> str | None:
        ident = self.view.identity
        return _attested(ident.postal_code) if ident else None

    def _link(self, host: str) -> str | None:
        ident = self.view.identity
        if ident is None:
            return None
        return next((l.url for l in ident.links if host in l.url.lower()), None)

    def _resolve_linkedin(self) -> str | None:
        return self._link("linkedin")

    def _resolve_github(self) -> str | None:
        return self._link("github")

    def _resolve_portfolio(self) -> str | None:
        ident = self.view.identity
        if ident is None:
            return None
        return next(
            (l.url for l in ident.links
             if "linkedin" not in l.url.lower() and "github" not in l.url.lower()),
            None,
        )

    def _resolve_work_authorized(self) -> str | None:
        auth = self.view.work_authorization
        if auth is None or not auth.legally_authorized_in:
            return None
        return "Yes"

    def _resolve_sponsorship(self) -> str | None:
        auth = self.view.work_authorization
        return _yes_no(auth.requires_sponsorship) if auth else None

    def _resolve_start_date(self) -> str | None:
        avail = self.view.availability
        if avail is None:
            return None
        return _iso(avail.earliest_start_date) or avail.notice_period

    def _resolve_salary_expectation(self) -> str | None:
        comp = self.view.compensation
        if comp is None or comp.expectation is None:
            return None
        return f"{comp.expectation}"

    def _resolve_current_salary(self) -> str | None:
        return None  # deliberately never proposed

    def _resolve_gender(self) -> str | None:
        d = self.view.disclosure
        return d.gender if d else VoluntaryDisclosure().gender

    def _resolve_race(self) -> str | None:
        d = self.view.disclosure
        return d.race_ethnicity if d else VoluntaryDisclosure().race_ethnicity

    def _resolve_veteran(self) -> str | None:
        d = self.view.disclosure
        return d.veteran_status if d else VoluntaryDisclosure().veteran_status

    def _resolve_disability(self) -> str | None:
        d = self.view.disclosure
        return d.disability_status if d else VoluntaryDisclosure().disability_status

    def _resolve_age_18(self) -> str | None:
        s = self.view.standard
        return _yes_no(s.age_18_or_over) if s else None

    def _resolve_background_check(self) -> str | None:
        s = self.view.standard
        return _yes_no(s.background_check_consent) if s else None

    def _resolve_criminal_record(self) -> str | None:
        return None  # the user answers this themselves

    def _resolve_previously_employed(self) -> str | None:
        s = self.view.standard
        return _yes_no(s.previously_employed_here) if s else None

    def _resolve_how_heard(self) -> str | None:
        s = self.view.standard
        return s.how_did_you_hear if s else None
