"""Source-only PICO contract. All keys required; unknown values explicit.

The extraction DTO contains no summaries, appraisal grades, calculated effects,
normalized ontology IDs, embedding scores or graph inference edges.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .numeric_tokens import parse_numeric_token, parse_count_token

Text = Annotated[str, Field(min_length=1, max_length=2000)]
ID = Annotated[str, Field(min_length=1, max_length=160)]
Number = Annotated[float, Field(allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class EvidenceSpan(StrictModel):
    source_id: ID
    section: Literal[
        "title",
        "abstract",
        "methods",
        "results",
        "table",
        "figure",
        "supplement",
        "dataset",
        "other",
    ]
    start: Count
    end: Annotated[int, Field(gt=0)]
    quote: Annotated[str, Field(min_length=1, max_length=12000)]
    page: Annotated[int, Field(ge=1)] | None
    table_or_figure: Text | None
    row: Text | None
    column: Text | None

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError(
                "Span must use exact Unicode code-point offsets [start, end)"
            )
        return self


class Reported(StrictModel, Generic[T]):
    """raw is the exact source token/phrase; confidence is uncalibrated, not certainty."""

    value: T | None
    raw: Text | None
    missing_reason: (
        Literal["not_reported", "not_applicable", "ambiguous", "not_reached"] | None
    )
    evidence: list[EvidenceSpan]
    extraction_confidence: Probability | None

    @model_validator(mode="after")
    def provenance(self):
        if self.value is not None:
            if self.missing_reason is not None or not self.raw or not self.evidence:
                raise ValueError(
                    "Reported values need raw text and evidence, with no missing reason"
                )
            if not any(self.raw in span.quote for span in self.evidence):
                raise ValueError("Raw token must occur in its cited passage")
            if isinstance(self.value, str) and self.value != self.raw:
                raise ValueError("Text facts must copy the exact source wording")
            if isinstance(self.value, (int, float)):
                try:
                    parsed = (
                        parse_count_token(self.raw)
                        if isinstance(self.value, int)
                        else parse_numeric_token(self.raw)
                    )
                except ValueError:
                    raise ValueError(
                        "Numeric raw token must be a number; keep units in separate fields"
                    )
                if parsed != self.value:
                    raise ValueError(
                        "Numeric value must match its literal source token; no conversion"
                    )
        elif self.missing_reason is None:
            raise ValueError("Null requires an explicit missing reason")
        if (
            self.value is None
            and self.missing_reason == "not_reached"
            and (not self.raw or not self.evidence)
        ):
            raise ValueError("Not reached requires a retained source passage")
        return self


class Quantity(StrictModel):
    amount: Reported[Number]
    unit: Reported[Text]


class SampleSize(StrictModel):
    count: Reported[Count]
    basis: Literal[
        "screened",
        "enrolled",
        "randomized",
        "analyzed",
        "completed",
        "events",
        "clusters",
        "studies",
        "not_reported",
    ]
    unit: Literal[
        "participants",
        "clusters",
        "studies",
        "specimens",
        "observations",
        "not_reported",
    ]


class Demographic(StrictModel):
    characteristic: Reported[Text]
    category: Reported[Text]
    statistic: Literal[
        "mean",
        "median",
        "minimum",
        "maximum",
        "sd",
        "iqr_lower",
        "iqr_upper",
        "count",
        "percent",
        "proportion",
        "reported_label",
    ]
    numeric_value: Reported[Number]
    unit: Reported[Text]
    denominator: Reported[Count]

    @model_validator(mode="after")
    def bounds(self):
        v = self.numeric_value.value
        if v is not None:
            if self.statistic == "percent" and not 0 <= v <= 100:
                raise ValueError("Invalid percentage")
            if self.statistic == "proportion" and not 0 <= v <= 1:
                raise ValueError("Invalid proportion")
            if self.statistic in ("sd", "count") and v < 0:
                raise ValueError("Negative SD/count")
            if self.statistic == "count" and (
                v != int(v)
                or (self.denominator.value is not None and v > self.denominator.value)
            ):
                raise ValueError("Invalid demographic count/denominator")
        return self


class Population(StrictModel):
    id: ID
    parent_population_id: ID | None
    label: Reported[Text]
    species: Reported[Text]
    conditions: list[Reported[Text]]
    inclusion_criteria: list[Reported[Text]]
    exclusion_criteria: list[Reported[Text]]
    settings: list[Reported[Text]]
    countries: list[Reported[Text]]
    sample_sizes: list[SampleSize]
    demographics: list[Demographic]


class Dosing(StrictModel):
    dose: Quantity
    dose_basis: Reported[Text]  # e.g. per kg; do not silently convert mg/kg to mg
    route: Reported[Text]
    frequency: Reported[Text]
    duration: Quantity
    titration: list[Reported[Text]]


class Exposure(StrictModel):
    id: ID
    kind: Literal[
        "drug",
        "supplement",
        "biomarker",
        "procedure",
        "screening",
        "behavioral",
        "placebo",
        "usual_care",
        "no_intervention",
        "other",
        "not_reported",
    ]
    name: Reported[Text]
    formulation: Reported[Text]
    dosing: list[Dosing]
    assay: Reported[Text]
    measurement_unit: Reported[Text]
    reference_category: Reported[Text]
    increment: Quantity | None


class Arm(StrictModel):
    id: ID
    label: Reported[Text]
    population_id: ID
    exposure_ids: list[ID]
    sample_sizes: list[SampleSize]
    period: Reported[Text]


class OutcomeDefinition(StrictModel):
    id: ID
    name: Reported[Text]
    definition: Reported[Text]
    components: list[Reported[Text]]
    instrument: Reported[Text]
    unit: Reported[Text]
    role: Literal["primary", "secondary", "exploratory", "safety", "not_reported"]
    role_evidence: list[EvidenceSpan]
    favorable_direction: Literal["higher", "lower", "context_dependent", "not_reported"]
    direction_evidence: list[EvidenceSpan]

    @model_validator(mode="after")
    def coded_evidence(self):
        if self.role != "not_reported" and not self.role_evidence:
            raise ValueError("Outcome role needs evidence")
        if self.favorable_direction != "not_reported" and not self.direction_evidence:
            raise ValueError(
                "Favorable direction cannot be inferred without source evidence"
            )
        return self


class Interval(StrictModel):
    kind: Literal["confidence", "credible", "prediction"]
    lower: Reported[Number]
    upper: Reported[Number]
    level_percent: Reported[Annotated[float, Field(gt=0, lt=100, allow_inf_nan=False)]]
    sidedness: Literal[
        "two_sided", "lower_one_sided", "upper_one_sided", "not_reported"
    ]
    method: Reported[Text]

    @model_validator(mode="after")
    def bounds(self):
        if self.method.value and re.search(
            r"\b(?:IQR|interquartile)\b", self.method.value, re.IGNORECASE
        ):
            raise ValueError("An interquartile range is not an uncertainty interval")
        lo, hi = self.lower.value, self.upper.value
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("Reversed interval")
        if self.sidedness == "two_sided" and (lo is None or hi is None):
            raise ValueError("Two-sided interval needs both bounds")
        if self.sidedness == "lower_one_sided" and (lo is None or hi is not None):
            raise ValueError("Invalid lower one-sided interval")
        if self.sidedness == "upper_one_sided" and (hi is None or lo is not None):
            raise ValueError("Invalid upper one-sided interval")
        return self


class PValue(StrictModel):
    comparator: Literal["eq", "lt", "le", "gt", "ge", "not_reported"]
    value: Reported[Probability]
    test: Reported[Text]
    sidedness: Literal["one_sided", "two_sided", "not_reported"]
    multiplicity: Literal["adjusted", "unadjusted", "not_reported"]
    adjustment_method: Reported[Text]
    reported_alpha: Reported[Probability]
    evidence: list[EvidenceSpan]  # retain inequality/operator, not only numeric token

    @model_validator(mode="after")
    def operator(self):
        if self.value.value is None and self.comparator != "not_reported":
            raise ValueError("Absent p-value must not have an operator")
        if self.value.value is not None and (
            self.comparator == "not_reported" or not self.evidence
        ):
            raise ValueError("p-value requires its operator and source context")
        return self


Metric = Literal[
    "hazard_ratio",
    "risk_ratio",
    "odds_ratio",
    "rate_ratio",
    "mean_difference",
    "standardized_mean_difference",
    "risk_difference",
    "regression_coefficient",
    "correlation",
    "sensitivity",
    "specificity",
    "auc",
    "c_index",
    "c_index_change",
    "nri",
    "partial_eta_squared",
    "mean",
    "median",
    "proportion",
    "percent",
    "event_count",
    "other",
]


class ArmResult(StrictModel):
    arm_id: ID
    n_analyzed: Reported[Count]
    events: Reported[Count]
    mean: Reported[Number]
    sd: Reported[Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    median: Reported[Number]
    person_time: Quantity | None

    @model_validator(mode="after")
    def denominator(self):
        if (
            self.events.value is not None
            and self.n_analyzed.value is not None
            and self.events.value > self.n_analyzed.value
        ):
            raise ValueError(
                "Participant event count exceeds denominator; recurrent events require a separate outcome"
            )
        return self


class StatisticalResult(StrictModel):
    id: ID
    outcome_id: ID
    population_id: ID
    index_arm_id: ID | None
    reference_arm_id: ID | None
    contrast: Reported[Text]
    timepoint: Quantity | None
    followup: Quantity | None
    analysis_set: Reported[Text]  # ITT, per-protocol, safety, source wording
    subgroup: list[Reported[Text]]
    metric: Metric
    metric_evidence: list[EvidenceSpan]
    estimate: Reported[Number]
    unit: Reported[Text]
    scale: Literal["natural", "log", "log10", "not_reported"]
    intervals: list[Interval]
    p_values: list[PValue]
    standard_error: Reported[Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    adjusted: Literal["adjusted", "unadjusted", "not_reported"]
    covariates: list[Reported[Text]]
    model: Reported[Text]
    arm_results: list[ArmResult]
    estimate_origin: Literal["reported"]

    @model_validator(mode="after")
    def statistics(self):
        if self.estimate.value is not None and not self.metric_evidence:
            raise ValueError("Metric needs evidence")
        if self.index_arm_id is not None and self.index_arm_id == self.reference_arm_id:
            raise ValueError("Identical contrast arms")
        values = [
            self.estimate.value,
            *[
                v
                for interval in self.intervals
                for v in (interval.lower.value, interval.upper.value)
            ],
        ]
        values = [v for v in values if v is not None]
        if self.scale == "natural":
            if self.metric in (
                "hazard_ratio",
                "risk_ratio",
                "odds_ratio",
                "rate_ratio",
            ) and any(v <= 0 for v in values):
                raise ValueError("Nonpositive natural ratio")
            maximum = (
                100 if self.unit.value in ("%", "percent", "percentage points") else 1
            )
            if self.metric in (
                "sensitivity",
                "specificity",
                "auc",
                "c_index",
                "partial_eta_squared",
                "proportion",
            ) and any(not 0 <= v <= maximum for v in values):
                raise ValueError("Invalid bounded measure in reported units")
            if self.metric == "percent" and any(not 0 <= v <= 100 for v in values):
                raise ValueError("Invalid percent")
            if self.metric == "correlation" and any(not -1 <= v <= 1 for v in values):
                raise ValueError("Invalid correlation")
        # Do not universally require estimate inside interval: some legitimate
        # bootstrap/credible intervals need method-aware downstream validation.
        return self


class ReportedSynthesis(StrictModel):
    result_id: ID
    included_studies: Reported[Count]
    participants: Reported[Count]
    model: Reported[Text]
    i_squared_percent: Reported[
        Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    ]
    tau_squared: Reported[Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    cochran_q: Reported[Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    q_degrees_freedom: Reported[Count]
    heterogeneity_p: PValue | None
    included_source_identifiers: list[Reported[Text]]


class MethodologyFact(StrictModel):
    domain: Literal[
        "randomization",
        "allocation_concealment",
        "blinding",
        "attrition",
        "missing_data",
        "outcome_measurement",
        "selective_reporting",
        "registration",
        "funding",
        "conflicts_of_interest",
        "crossover",
        "clustering",
        "other",
    ]
    fact: Reported[Text]  # exact wording only, never a generated RoB judgment


class PICOExtraction(StrictModel):
    schema_version: Literal["clarity-pico-1.0"]
    document_kind: Literal[
        "results_report", "protocol", "aggregate_dataset", "not_determined"
    ]
    study_design: Literal[
        "rct_parallel",
        "rct_crossover",
        "rct_cluster",
        "meta_analysis",
        "systematic_review",
        "observational",
        "diagnostic_accuracy",
        "other",
        "not_determined",
    ]
    design_evidence: list[EvidenceSpan]
    study_identifiers: list[Reported[Text]]  # registry/cohort IDs, only if reported
    populations: list[Population]
    exposures: list[Exposure]
    arms: list[Arm]
    outcomes: list[OutcomeDefinition]
    results: list[StatisticalResult]
    reported_syntheses: list[ReportedSynthesis]
    methodology_facts: list[MethodologyFact]

    @model_validator(mode="after")
    def references(self):
        indexes = {}
        for field in ("populations", "exposures", "arms", "outcomes", "results"):
            items = getattr(self, field)
            ids = [x.id for x in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {field} ID")
            indexes[field] = set(ids)

        def require(value, kind):
            if value is not None and value not in indexes[kind]:
                raise ValueError(f"Unknown {kind} reference: {value}")

        for p in self.populations:
            require(p.parent_population_id, "populations")
            seen = {p.id}
            parent = p.parent_population_id
            while parent:
                if parent in seen:
                    raise ValueError("Population ancestry cycle")
                seen.add(parent)
                parent = next(
                    x.parent_population_id for x in self.populations if x.id == parent
                )
        for arm in self.arms:
            require(arm.population_id, "populations")
            for id in arm.exposure_ids:
                require(id, "exposures")
        for r in self.results:
            require(r.outcome_id, "outcomes")
            require(r.population_id, "populations")
            require(r.index_arm_id, "arms")
            require(r.reference_arm_id, "arms")
            for arm in r.arm_results:
                require(arm.arm_id, "arms")
        for synthesis in self.reported_syntheses:
            require(synthesis.result_id, "results")
        if self.document_kind == "protocol" and self.results:
            raise ValueError("Protocol targets are not observed results")
        if self.study_design != "not_determined" and not self.design_evidence:
            raise ValueError("Study design needs evidence")
        return self


class SourceDocument(StrictModel):
    """Trusted caller metadata; never request hashes or identifiers from the LLM."""

    id: ID
    kind: Literal["abstract", "full_text", "protocol", "aggregate_dataset"]
    pmid: Annotated[str, Field(pattern=r"^\d+$")] | None
    pmcid: Annotated[str, Field(pattern=r"^PMC\d+$")] | None
    doi: Annotated[str, Field(pattern=r"^10\.\d{4,9}/\S+$")] | None
    source_url: Text | None
    version: Text
    retrieved_at: datetime
    text: Annotated[str, Field(min_length=1)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def integrity(self):
        if self.retrieved_at.tzinfo is None:
            raise ValueError("Timezone required")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("Source hash mismatch")
        return self


class ExtractionEnvelope(StrictModel):
    """Server-owned audit envelope around the untrusted structured model output."""

    run_id: ID
    extracted_at: datetime
    provider: Literal["openai", "anthropic", "fixture"]
    model: Text
    prompt_version: Text
    schema_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    request_id: ID | None
    sources: list[SourceDocument]
    extraction: PICOExtraction

    @model_validator(mode="after")
    def source_integrity(self):
        if self.extracted_at.tzinfo is None:
            raise ValueError("Timezone required")
        validate_sources(self.extraction, self.sources)
        return self


def validate_sources(extraction: PICOExtraction, sources: list[SourceDocument]) -> None:
    """Run after schema parsing and BEFORE accepting an extraction artifact."""
    index = {s.id: s for s in sources}
    if len(index) != len(sources):
        raise ValueError("Duplicate source ID")

    def visit(node):
        if isinstance(node, EvidenceSpan):
            source = index.get(node.source_id)
            if source is None or source.text[node.start : node.end] != node.quote:
                raise ValueError(
                    "Source span is missing or differs from immutable text"
                )
        elif isinstance(node, BaseModel):
            for field in type(node).model_fields:
                visit(getattr(node, field))
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(extraction)
