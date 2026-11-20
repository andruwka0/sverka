import re
from collections import defaultdict

from rapidfuzz.distance import JaroWinkler, Levenshtein

from radar.config import Rules
from radar.models import (
    ROLES,
    Alert,
    CheckResult,
    Diagnostic,
    InputError,
    Match,
    Record,
    Summary,
)


def _clean(value: str) -> str:
    value = value.strip()
    if value.startswith("**") and value.endswith("**"):
        value = value[2:-2].strip()
    return "" if value == "-" else value


def _phone(value: str) -> str:
    value = re.sub(r"[\s()\-]", "", _clean(value)).removeprefix("+")
    if re.fullmatch(r"[78][0-9]{10}", value):
        return "7" + value[1:]
    return ""


ADDRESS_WORDS = {
    "улица": "ул",
    "дом": "д",
    "офис": "оф",
    "корпус": "корп",
    "к": "корп",
    "квартира": "кв",
    "проспект": "пр",
    "город": "г",
}


def _address(value: str) -> str:
    value = _clean(value).lower().replace("ё", "е")
    value = re.sub(r"пр-т\b", "пр", value)
    value = re.sub(r"\bк(?=\s*\d)", "корп ", value)
    value = re.sub(
        r"\b(дом|д|корпус|корп|квартира|кв|офис|оф)([.\s]*)(\d+)\s+([а-яa-z])\b",
        r"\1 \3\4",
        value,
    )
    value = re.sub(r"\b(дом|д|корпус|корп|квартира|кв|офис|оф)(?=\d)", r"\1 ", value)
    value = re.sub(r"(\d)-(?=[а-яa-z]\b)", r"\1", value)
    # Split a house number from an attached suffix marker, e.g. 10к2.
    value = re.sub(r"(\d)(к)(?=\d)", r"\1 корп ", value)
    words = re.findall(r"[\w/\-]+", value)
    return " ".join(ADDRESS_WORDS.get(word, word) for word in words)


def _address_similarity(left: str, right: str) -> float | None:
    def numbers(address):
        return dict(
            re.findall(
                r"\b(д|корп|кв|оф)\s*(\d+[а-яa-z]?(?:[/-]\d+[а-яa-z]?)?)\b", address
            )
        )

    a, b = numbers(left), numbers(right)
    if any(a[key] != b[key] for key in a.keys() & b.keys()):
        return None
    return Levenshtein.normalized_similarity(left, right)


def _name(value: str) -> str:
    return " ".join(
        re.sub(r"[.]", " ", _clean(value).lower().replace("ё", "е")).split()
    )


def _name_similarity(left: str, right: str) -> float | None:
    a, b = left.split(), right.split()
    if len(a) < 2 or len(b) < 2:
        return None
    if not all(token[0].isalpha() for token in a + b):
        return None
    if any(x[0] != y[0] for x, y in zip(a[1:], b[1:])):
        return None
    return JaroWinkler.normalized_similarity(left, right)


def _matches(participant: Record, relative: Record, rules: Rules) -> list[Match]:
    results = []
    for rule in rules.rules:
        if rule.id == "R1_PHONE_MATCH":
            field, normalize, similarity = "phone", _phone, None
        elif rule.id == "R2_ADDRESS_MATCH":
            field, normalize, similarity = "address", _address, _address_similarity
        else:
            field, normalize, similarity = "director_name", _name, _name_similarity
        right_field = "full_name" if field == "director_name" else field
        left_raw, right_raw = participant.values[field], relative.values[right_field]
        left, right = normalize(left_raw), normalize(right_raw)
        if not left or not right:
            continue
        score = similarity(left, right) if similarity else None
        passes = (
            (left == right)
            if similarity is None
            else (score is not None and score >= rule.cutoff)
        )
        if passes:
            results.append(
                Match(
                    rule_id=rule.id,
                    points=rule.weight,
                    left_field=f"participants.{field}",
                    right_field=f"related_persons.{right_field}",
                    left_raw=left_raw,
                    right_raw=right_raw,
                    left_normalized=left,
                    right_normalized=right,
                    similarity=score,
                )
            )
    return results


def compare(tables: dict[str, list[Record]], rules: Rules) -> CheckResult:
    """Compare source records without mutating inputs or writing files."""
    warnings, errors = [], []
    skipped = dict.fromkeys(ROLES, 0)
    valid = {}
    keys = {
        "participants": ("participant_id", "tender_id"),
        "officials": ("official_id", "tender_id"),
        "related_persons": ("official_id",),
    }
    for role in ROLES:
        valid[role] = []
        seen = {}
        for record in tables[role]:
            key = tuple(_clean(record.values[field]) for field in keys[role])
            if not all(key):
                skipped[role] += 1
                field = next(
                    field for field in keys[role] if not _clean(record.values[field])
                )
                warnings.append(
                    Diagnostic(
                        code="missing_key",
                        file_role=role,
                        row=record.source.row,
                        field=field,
                        message="Пропущена строка без обязательного ключа",
                    )
                )
                continue
            if role != "related_persons" and key in seen:
                errors.append(
                    Diagnostic(
                        code="duplicate_key",
                        file_role=role,
                        field=",".join(keys[role]),
                        rows=[seen[key], record.source.row],
                        message="Ключ повторяется в строках",
                    )
                )
            seen[key] = record.source.row
            valid[role].append(record)
    if errors:
        raise InputError(errors)
    officials = defaultdict(list)
    participants = defaultdict(list)
    for official in valid["officials"]:
        officials[_clean(official.values["official_id"])].append(official)
    for participant in valid["participants"]:
        participants[_clean(participant.values["tender_id"])].append(participant)
    alerts = []
    for relative in valid["related_persons"]:
        linked = officials[_clean(relative.values["official_id"])]
        if not linked:
            skipped["related_persons"] += 1
            warnings.append(
                Diagnostic(
                    code="unknown_official",
                    file_role="related_persons",
                    field="official_id",
                    row=relative.source.row,
                    message="Сотрудник с указанным official_id отсутствует",
                )
            )
        for official in linked:
            tender = _clean(official.values["tender_id"])
            for participant in participants[tender]:
                matches = _matches(participant, relative, rules)
                if matches:
                    score = sum(match.points for match in matches)
                    alerts.append(
                        Alert(
                            tender_id=tender,
                            participant=participant.values,
                            official=official.values,
                            related_person=relative.values,
                            score=score,
                            level=rules.alert_levels.classify(score),
                            sources=[
                                participant.source,
                                official.source,
                                relative.source,
                            ],
                            matches=matches,
                        )
                    )
    alerts.sort(
        key=lambda a: (
            -a.score,
            a.tender_id,
            _clean(a.participant["participant_id"]),
            _clean(a.official["official_id"]),
            a.sources[2].row,
        )
    )
    return CheckResult(
        summary=Summary(
            rows_read={role: len(tables[role]) for role in ROLES},
            rows_skipped=skipped,
            alert_count=len(alerts),
        ),
        alerts=alerts,
        warnings=warnings,
    )
