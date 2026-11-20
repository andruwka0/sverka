import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

PREFIXES = {
    "R1_PHONE_MATCH": "exact",
    "R2_ADDRESS_MATCH": "fuzzy_",
    "R3_NAME_FUZZY": "jaro_winkler_",
}


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in keys:
                raise ValueError(f"Invalid or duplicate YAML key: {key!r}")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Literal["R1_PHONE_MATCH", "R2_ADDRESS_MATCH", "R3_NAME_FUZZY"]
    description: str
    weight: StrictInt = Field(gt=0)
    threshold: str

    @model_validator(mode="after")
    def check_threshold(self):
        prefix = PREFIXES[self.id]
        if self.id == "R1_PHONE_MATCH":
            valid = self.threshold == prefix
        else:
            match = re.fullmatch(
                re.escape(prefix) + r"(0(?:\.\d+)?|1(?:\.0+)?)", self.threshold
            )
            valid = match is not None
        if not valid:
            raise ValueError(
                f"{self.id}.threshold: unsupported threshold {self.threshold!r}"
            )
        return self

    @property
    def cutoff(self) -> float:
        return float(self.threshold.removeprefix(PREFIXES[self.id]))


class Levels(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    high: str
    medium: str
    low: str

    @model_validator(mode="after")
    def check_levels(self):
        values = []
        for field, operator in [("high", ">="), ("medium", ">="), ("low", "<")]:
            match = re.fullmatch(
                re.escape(operator) + r"\s*(\d+)", getattr(self, field)
            )
            if not match:
                raise ValueError(f"alert_levels.{field}: expected {operator} integer")
            values.append(int(match[1]))
        if not (values[0] > values[1] == values[2] > 0):
            raise ValueError("alert_levels: require high > medium = low > 0")
        return self

    def classify(self, score: int) -> Literal["high", "medium", "low"]:
        if score >= int(self.high.removeprefix(">=")):
            return "high"
        if score >= int(self.medium.removeprefix(">=")):
            return "medium"
        return "low"


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rules: tuple[Rule, ...]
    alert_levels: Levels

    @model_validator(mode="after")
    def check_ids(self):
        if len(self.rules) != 3 or {r.id for r in self.rules} != set(PREFIXES):
            raise ValueError(
                "rules.id: require each of the three rule IDs exactly once"
            )
        return self


def load_rules(path: Path) -> Rules:
    try:
        return Rules.model_validate(
            yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        )
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise ValueError(f"Invalid rules configuration {path}: {exc}") from exc
