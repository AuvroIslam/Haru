"""Text analysis for the fact-boundary validator.

The problem this solves is narrower than it looks. We are not trying to
understand prose — we are trying to answer one question about each named
entity: *is the writer claiming this as their own?*

Three things must be told apart, and the corpus has a case for each:

    "Operated production Kubernetes clusters"        → a claim
    "should transfer well to your Kubernetes stack"  → someone else's
    "I have not worked with Kubernetes"              → explicitly disclaimed

Only the first is checked against the boundary. Getting this wrong in the
permissive direction lets a fabrication through; getting it wrong in the strict
direction blocks honest writing, which is worse than it sounds — a validator
that cries wolf gets switched off, and then it protects nobody.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from haru.brain.fact_boundary import normalize
from haru.validation.lexicon import ALIASES, RUN_CONNECTORS

#: Keeps %, /, +, # and . attached so "40%", "rows/sec", "C++", "C#" and
#: "Node.js" survive tokenisation intact.
_TOKEN = re.compile(r"[A-Za-z0-9][\w%/+#.\-']*")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_NUMBER = re.compile(r"^\d[\d,]*\.?\d*%?$")
_YEAR = re.compile(r"^(19|20)\d{2}$")

#: Titlecase at the start of a sentence means grammar, not a proper noun. These
#: never begin or extend a named-entity run.
FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "i", "a", "an", "the", "this", "that", "these", "those", "my", "our",
        "your", "his", "her", "their", "its", "we", "you", "they", "he", "she",
        "it", "in", "on", "at", "by", "to", "for", "with", "from", "as", "of",
        "and", "or", "but", "if", "then", "than", "so", "not", "no", "is",
        "was", "were", "are", "am", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "can", "could", "should",
        "may", "might", "must", "shall", "there", "here", "when", "where",
        "while", "after", "before", "during", "through", "over", "under",
        "about", "into", "onto", "up", "down", "out", "off", "again", "also",
        "very", "more", "most", "much", "many", "some", "any", "all", "both",
        "each", "every", "other", "another", "such", "own", "same", "just",
        "only", "even", "still", "yet", "because", "since", "although",
        "though", "however", "therefore", "dear", "hello", "hi", "thanks",
        "thank", "sincerely", "regards", "best", "please", "let", "made",
        "make", "built", "build", "worked", "work", "used", "use", "using",
        "led", "lead", "ran", "run", "wrote", "write", "cut", "reduced",
        "increased", "improved", "shipped", "deep", "senior", "junior", "lead",
        "staff", "principal", "backend", "frontend", "fullstack", "computer",
        "software", "data", "machine", "operated", "sustained", "managed",
        "designed", "developed", "created", "delivered", "maintained",
    }
)

#: Negation cues. Seeing one shortly before an entity means it is disclaimed.
_NEGATIONS: frozenset[str] = frozenset(
    {"not", "no", "never", "without", "unfamiliar", "lack", "lacking", "yet"}
)

#: Possessives that attribute an entity to someone other than the writer.
_THIRD_PARTY: frozenset[str] = frozenset({"your", "their", "its", "his", "her"})

#: How far back to look for a negation or possessive cue.
_LOOKBACK = 5


@dataclass(frozen=True)
class Mention:
    """A named entity found in text, with how it was used."""

    text: str
    disclaimed: bool = False
    third_party: bool = False

    @property
    def is_claim(self) -> bool:
        return not (self.disclaimed or self.third_party)

    @property
    def key(self) -> str:
        return canonical(self.text)


def canonical(term: str) -> str:
    """Normalise, then resolve spelling aliases.

    ``postgres`` and ``PostgreSQL`` must reach the boundary as the same term,
    or someone who genuinely knows PostgreSQL gets told they are lying.
    """
    key = normalize(term)
    return ALIASES.get(key, key)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


#: Trailing punctuation swallowed by the token pattern. It must come off before
#: matching, or "85%." fails the number test and "2019." fails the year test —
#: which silently turns a fabricated metric into an unchecked one.
_TRAILING = ".,;:!?'\"-"


def tokenize(text: str) -> list[str]:
    """Split into tokens, keeping internal punctuation but dropping trailing.

    ``Node.js`` and ``rows/sec`` survive intact; ``85%.`` becomes ``85%``.
    """
    return [t for t in (raw.rstrip(_TRAILING) for raw in _TOKEN.findall(text)) if t]


def _is_entity_token(token: str, *, first_in_sentence: bool) -> bool:
    """Could this token be part of a proper noun?"""
    if len(token) < 2:
        return False
    if token.lower() in FUNCTION_WORDS:
        return False
    if token.isupper():
        return True  # acronyms are entities wherever they appear
    if not token[0].isupper():
        return False
    # Titlecase at sentence start is grammar; elsewhere it suggests a name.
    return not first_in_sentence


def find_mentions(text: str) -> list[Mention]:
    """Extract named entities, tagged with how they are being used."""
    found: list[Mention] = []

    for sentence in sentences(text):
        tokens = tokenize(sentence)
        index = 0
        while index < len(tokens):
            if not _is_entity_token(tokens[index], first_in_sentence=index == 0):
                index += 1
                continue

            run = [tokens[index]]
            cursor = index + 1
            while cursor < len(tokens):
                token = tokens[cursor]
                if _is_entity_token(token, first_in_sentence=False):
                    run.append(token)
                    cursor += 1
                elif (
                    token.lower() in RUN_CONNECTORS
                    and cursor + 1 < len(tokens)
                    and _is_entity_token(tokens[cursor + 1], first_in_sentence=False)
                ):
                    run.extend([token, tokens[cursor + 1]])
                    cursor += 2
                else:
                    break

            context = [t.lower().rstrip(",.;:") for t in tokens[max(0, index - _LOOKBACK) : index]]
            found.append(
                Mention(
                    text=" ".join(run).rstrip(",.;:"),
                    disclaimed=any(word in _NEGATIONS for word in context),
                    third_party=any(word in _THIRD_PARTY for word in context),
                )
            )
            index = cursor

    return found


def find_lowercase_tech(text: str, vocabulary: frozenset[str]) -> list[Mention]:
    """Catch technology names written in lowercase.

    Capitalisation finds most fabricated entities. This finds the rest, for the
    subset of technologies we can name in advance.
    """
    found: list[Mention] = []
    for sentence in sentences(text):
        tokens = tokenize(sentence)
        for position, token in enumerate(tokens):
            if token[0].isupper():
                continue
            if canonical(token) not in vocabulary:
                continue
            context = [
                t.lower().rstrip(",.;:")
                for t in tokens[max(0, position - _LOOKBACK) : position]
            ]
            found.append(
                Mention(
                    text=token.rstrip(",.;:"),
                    disclaimed=any(word in _NEGATIONS for word in context),
                    third_party=any(word in _THIRD_PARTY for word in context),
                )
            )
    return found


def find_numeric_claims(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Find figures cited in the text.

    Returns each number with the candidate spans it might belong to — the
    number alone, plus the next one and two tokens. A metric counts as
    supported if *any* span matches something the user has verified, so
    "40% faster" is recognised whether stored as "40%" or "40% faster".

    Four-digit years are skipped: dates are not performance claims.
    """
    claims: list[tuple[str, tuple[str, ...]]] = []
    for sentence in sentences(text):
        tokens = tokenize(sentence)
        for position, token in enumerate(tokens):
            if not _NUMBER.match(token):
                continue
            if _YEAR.match(token.rstrip("%")):
                continue
            spans = tuple(
                " ".join(tokens[position : position + length]).rstrip(",.;:")
                for length in (1, 2, 3)
                if position + length <= len(tokens)
            )
            claims.append((token, spans))
    return claims


def find_credential_claims(text: str, markers: tuple[str, ...]) -> list[Mention]:
    """Find assertions of holding a certification.

    A named credential comes back as its full title. A vague one — "I am a
    certified cloud professional" — comes back as an empty-text mention, which
    the validator treats as unverifiable rather than ignorable.
    """
    lowered = text.lower()
    if not any(marker in lowered for marker in markers):
        return []

    named = [
        mention
        for mention in find_mentions(text)
        if any(marker in mention.text.lower() for marker in markers)
    ]
    return named or [Mention(text="")]


def contains_phrase(text: str, phrase: str) -> bool:
    """Substring match on lowered text, used for leak phrases and clichés."""
    return phrase in text.lower()
