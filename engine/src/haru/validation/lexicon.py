"""Word lists and term-handling rules for the validator.

Written for Haru. ApplyPilot demonstrated the *categories* worth checking —
LLM clichés, model self-talk, unverifiable credentials — but its lists are
AGPL-licensed text, so none of it is reproduced here.

Three lists carry real risk if they drift:

``GENERIC_TECH``  terms that are architectural vocabulary rather than owned
                  skills. "REST" in "built REST services" is not a claim about
                  a product; flagging it would block honest prose.
``ALIASES``       spelling variants that mean the same thing. Without these the
                  validator rejects "postgres" from someone who has PostgreSQL,
                  which teaches users that it cries wolf.
``KNOWN_TECH``    lowercase technology names worth checking. Capitalisation
                  finds most fabrications; this catches the lowercase ones.
"""

from __future__ import annotations

# ── Clichés ──────────────────────────────────────────────────────────────
# Phrases that mark text as machine-written. Blocking in strict mode, warnings
# in normal mode (PRD §10.2).

CLICHES: frozenset[str] = frozenset(
    {
        # Self-description that says nothing
        "passionate",
        "highly motivated",
        "self-starter",
        "go-getter",
        "team player",
        "detail-oriented",
        "results-driven",
        "results-oriented",
        "hard-working",
        "fast learner",
        "quick learner",
        "strong communicator",
        "dynamic professional",
        "seasoned professional",
        # Inflated verbs
        "spearheaded",
        "spearheading",
        "orchestrated",
        "championed",
        "pioneered",
        "helmed",
        "masterminded",
        # Empty intensifiers
        "cutting-edge",
        "state-of-the-art",
        "best-in-class",
        "world-class",
        "industry-leading",
        "next-generation",
        "game-changing",
        "revolutionary",
        # Unfalsifiable claims
        "proven track record",
        "track record of success",
        "demonstrated ability",
        "extensive experience",
        "deep understanding",
        "comprehensive knowledge",
        "well-versed in",
        "adept at",
        "thrives in",
        "excels at",
        # Consultant filler
        "synergy",
        "synergies",
        "holistic approach",
        "paradigm shift",
        "value-add",
        "leverage my",
        "leveraging my",
        "wheelhouse",
        "move the needle",
        "low-hanging fruit",
        # Letter padding
        "i am excited to",
        "i am thrilled to",
        "i would be a great fit",
        "perfect candidate",
        "dream job",
        "i believe i would",
    }
)


# ── Model leakage ────────────────────────────────────────────────────────
# The model addressing its operator inside the deliverable. Always blocking —
# this is output corruption, not a matter of taste.
#
# Patterns are matched as substrings against lowercased text, so each must be
# specific enough not to fire on ordinary prose. "note" alone would match
# "I note that…"; "note:" would not.

LEAK_PHRASES: tuple[str, ...] = (
    "here is the revised",
    "here is the updated",
    "here is the corrected",
    "here is the rewritten",
    "here's the revised",
    "here's the updated",
    "here is a revised",
    "below is the revised",
    "the following is the revised",
    "as requested",
    "per your request",
    "per your feedback",
    "based on your feedback",
    "as per the instructions",
    "i apologize",
    "i apologise",
    "i am sorry",
    "my apologies",
    "apologies for",
    "i made an error",
    "i have updated this",
    "i have revised this",
    "i have rewritten",
    "i have removed",
    "i have corrected",
    "let me try again",
    "i will try again",
    "note:",
    "disclaimer:",
    "important:",
    "caveat:",
    "[insert",
    "[your name",
    "[company name",
    "lorem ipsum",
    "as an ai",
    "as a language model",
)


# ── Generic technical vocabulary ─────────────────────────────────────────
# Architectural concepts and protocols, not owned skills. Never treated as a
# claim, in either direction.

GENERIC_TECH: frozenset[str] = frozenset(
    {
        "rest",
        "restful",
        "api",
        "apis",
        "http",
        "https",
        "json",
        "xml",
        "yaml",
        "csv",
        "crud",
        "mvc",
        "orm",
        "sdk",
        "cli",
        "gui",
        "ui",
        "ux",
        "os",
        "tcp",
        "ip",
        "ssh",
        "url",
        "uri",
        "dns",
        "cdn",
        "saas",
        "paas",
        "iaas",
        "mvp",
        "poc",
        "qa",
        "eta",
        "faq",
        "pdf",
        "csv",
        "id",
        "ok",
    }
)


# ── Aliases ──────────────────────────────────────────────────────────────
# Left-hand side normalises to the right-hand side before boundary lookup.

ALIASES: dict[str, str] = {
    "postgres": "postgresql",
    "psql": "postgresql",
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "golang": "go",
    "node": "nodejs",
    "reactjs": "react",
    "vuejs": "vue",
    "postgressql": "postgresql",
    "mongo": "mongodb",
    "gcp": "googlecloud",
    "tf": "terraform",
    "k8": "kubernetes",
    "sklearn": "scikitlearn",
    "tf2": "tensorflow",
}


# ── Known lowercase technology names ─────────────────────────────────────
# Capitalisation catches most fabricated entities; these catch the ones written
# in lowercase. Deliberately not exhaustive — see the honesty note in
# validator.py about what this approach does and does not detect.

KNOWN_TECH: frozenset[str] = frozenset(
    {
        "python", "java", "javascript", "typescript", "ruby", "rust", "go",
        "kotlin", "swift", "scala", "perl", "php", "haskell", "elixir", "clojure",
        "django", "flask", "fastapi", "rails", "laravel", "spring", "express",
        "react", "angular", "vue", "svelte", "nextjs", "nuxt", "jquery",
        "nodejs", "deno", "bun",
        "postgresql", "mysql", "sqlite", "mongodb", "redis", "cassandra",
        "elasticsearch", "dynamodb", "snowflake", "bigquery",
        "docker", "kubernetes", "terraform", "ansible", "jenkins", "kafka",
        "rabbitmq", "nginx", "apache", "prometheus", "grafana",
        "aws", "azure", "gcp", "heroku", "vercel", "netlify", "cloudflare",
        "tensorflow", "pytorch", "keras", "pandas", "numpy", "scipy",
        "scikitlearn", "spark", "hadoop", "airflow", "dbt",
        "git", "linux", "bash", "graphql", "grpc", "webpack", "vite",
        "pytest", "jest", "cypress", "selenium", "playwright", "pydantic",
    }
)


#: Words that may sit inside a multi-word proper noun without breaking it —
#: "University of Dhaka", "Bank of America".
#:
#: "and" is deliberately absent. It joins two separate entities far more often
#: than it belongs to one name, and welding "Django and Spring Boot" into a
#: single term makes the violation message wrong even when the verdict is right.
RUN_CONNECTORS: frozenset[str] = frozenset(
    {"of", "for", "de", "van", "von", "der", "la", "le", "&"}
)


#: Job-title nouns. Skipped when they stand alone, so "Senior Engineer at
#: Google" reports Google rather than complaining about "Engineer" — but kept
#: inside longer names like "AWS Certified Solutions Architect".
ROLE_WORDS: frozenset[str] = frozenset(
    {
        "engineer", "engineering", "developer", "programmer", "manager",
        "analyst", "designer", "architect", "scientist", "consultant",
        "director", "officer", "specialist", "associate", "assistant",
        "intern", "internship", "lead", "head", "president", "founder",
        "cofounder", "owner", "administrator", "technician", "researcher",
        "coordinator", "supervisor", "executive", "partner", "advisor",
        "contractor", "freelancer", "graduate", "student", "candidate",
    }
)


#: Signals that a sentence names a certification.
CREDENTIAL_MARKERS: tuple[str, ...] = (
    "certified",
    "certification",
    "certificate",
    "accredited",
    "chartered",
    "licensed",
)
