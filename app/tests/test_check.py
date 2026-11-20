from pathlib import Path

from radar.config import load_rules
from radar.engine import compare
from radar.tables import read_csv

ROOT = Path(__file__).resolve().parents[1]


def demo():
    return {
        role: read_csv(ROOT / "data" / f"{role}.csv", role)
        for role in ("participants", "officials", "related_persons")
    }


def test_demo_returns_one_explained_alert():
    result = compare(demo(), load_rules(ROOT / "rules.yaml"))
    assert result.summary.rows_read == {
        "participants": 3,
        "officials": 2,
        "related_persons": 3,
    }
    assert result.summary.rows_skipped == {
        "participants": 0,
        "officials": 0,
        "related_persons": 0,
    }
    assert len(result.alerts) == 1
    alert = result.alerts[0]
    assert (
        alert.participant["participant_id"],
        alert.official["official_id"],
        alert.score,
        alert.level,
    ) == ("P002", "O001", 80, "high")
    assert alert.related_person["full_name"] == "Сидоров Д.П."
    assert [m.rule_id for m in alert.matches] == ["R1_PHONE_MATCH", "R2_ADDRESS_MATCH"]
    assert [source.row for source in alert.sources] == [3, 2, 3]


def test_reformatted_phone_preserves_evidence():
    tables = demo()
    tables["participants"][1].values["phone"] = "8 (916) 555-44-33"
    alert = compare(tables, load_rules(ROOT / "rules.yaml")).alerts[0]
    assert alert.score == 80
    assert alert.matches[0].left_raw == "8 (916) 555-44-33"
    assert alert.matches[0].left_normalized == "79165554433"


def test_procedure_membership_is_required():
    tables = demo()
    tables["participants"][1].values["tender_id"] = "T-2026-02"
    assert compare(tables, load_rules(ROOT / "rules.yaml")).alerts == []


def test_other_relatives_and_procedures_remain_distinct():
    from copy import deepcopy

    tables = demo()
    relative = deepcopy(tables["related_persons"][1])
    relative.source.row = 5
    tables["related_persons"].append(relative)
    official = deepcopy(tables["officials"][0])
    official.values["tender_id"] = "another"
    tables["officials"].append(official)
    participant = deepcopy(tables["participants"][1])
    participant.values["tender_id"] = "another"
    tables["participants"].append(participant)
    result = compare(tables, load_rules(ROOT / "rules.yaml"))
    assert len(result.alerts) == 4
    assert [a.tender_id for a in result.alerts] == [
        "T-2026-01",
        "T-2026-01",
        "another",
        "another",
    ]


def test_unknown_official_and_missing_keys_are_skipped_once():
    tables = demo()
    tables["related_persons"][1].values["official_id"] = "UNKNOWN"
    tables["participants"][0].values["tender_id"] = "-"
    result = compare(tables, load_rules(ROOT / "rules.yaml"))
    assert result.alerts == []
    assert result.summary.rows_skipped == {
        "participants": 1,
        "officials": 0,
        "related_persons": 1,
    }
    assert [(w.code, w.row) for w in result.warnings] == [
        ("missing_key", 2),
        ("unknown_official", 3),
    ]


def single_pair(phone="", address="", name=""):
    tables = demo()
    tables["participants"] = [tables["participants"][1]]
    tables["related_persons"] = [tables["related_persons"][1]]
    participant = tables["participants"][0]
    relative = tables["related_persons"][0]
    for field, value in [("phone", phone), ("address", address)]:
        participant.values[field] = relative.values[field] = value
    participant.values["director_name"] = relative.values["full_name"] = name
    return tables


def test_single_signals_get_correct_priority():
    rules = load_rules(ROOT / "rules.yaml")
    for kwargs, score, level in [
        ({"phone": "+79165554433"}, 50, "high"),
        ({"address": "Москва, д. 100 (БЦ Плаза)"}, 30, "medium"),
        ({"name": "Сидоров Д.П."}, 20, "low"),
    ]:
        alerts = compare(single_pair(**kwargs), rules).alerts
        assert [(a.score, a.level) for a in alerts] == [(score, level)]
    assert compare(single_pair(), rules).alerts == []


def test_conflicting_initials_and_house_numbers_are_rejected():
    tables = single_pair(name="Иванов И.И.", address="Москва, пр. Мира, д. 100")
    tables["related_persons"][0].values.update(
        full_name="Иванов П.И.", address="Москва, пр. Мира, д. 10"
    )
    assert compare(tables, load_rules(ROOT / "rules.yaml")).alerts == []


def test_configuration_controls_weights_and_inclusive_thresholds(tmp_path):
    import yaml

    original = yaml.safe_load((ROOT / "rules.yaml").read_text())
    original["rules"][0]["weight"] = 40
    config = tmp_path / "rules.yaml"
    config.write_text(yaml.safe_dump(original), encoding="utf-8")
    assert compare(demo(), load_rules(config)).alerts[0].score == 70
    assert (
        compare(single_pair(phone="+79165554433"), load_rules(config)).alerts[0].level
        == "medium"
    )
    # Levenshtein distance is 1 over 10 chars. Jaro-Winkler for ivanov a / ivanov ab is 44/45.
    for rule_index, kwargs, changed_field, changed_value, cutoff in [
        (1, {"address": "abcdefghij"}, "address", "abcdefghiX", "fuzzy_0.9"),
        (
            2,
            {"name": "ivanov a"},
            "full_name",
            "ivanov ab",
            "jaro_winkler_0.9777777777777777",
        ),
    ]:
        original["rules"][rule_index]["threshold"] = cutoff
        config.write_text(yaml.safe_dump(original), encoding="utf-8")
        tables = single_pair(**kwargs)
        tables["related_persons"][0].values[changed_field] = changed_value
        assert len(compare(tables, load_rules(config)).alerts) == 1
        prefix, number = cutoff.rsplit("_", 1)
        original["rules"][rule_index]["threshold"] = (
            f"{prefix}_{float(number) + 0.00001}"
        )
        config.write_text(yaml.safe_dump(original), encoding="utf-8")
        assert compare(tables, load_rules(config)).alerts == []


def test_compact_house_number_still_blocks_false_address_match():
    tables = single_pair(address="г. Москва, пр. Мира, д.10, офис 5")
    tables["related_persons"][0].values["address"] = (
        "г. Москва, пр. Мира, д.100, офис 5"
    )
    assert compare(tables, load_rules(ROOT / "rules.yaml")).alerts == []


def test_duplicate_yaml_keys_are_rejected(tmp_path):
    import pytest

    text = (
        (ROOT / "rules.yaml")
        .read_text()
        .replace("weight: 50", "weight: 50\n    weight: 10")
    )
    config = tmp_path / "rules.yaml"
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="weight"):
        load_rules(config)


def test_different_house_suffixes_and_compact_markers_block_match():
    for left, right in [
        ("д. 10-а", "д. 10-б"),
        ("дом10", "дом100"),
        ("д. 10А", "д. 10Б"),
    ]:
        tables = single_pair(address=f"Москва, улица Пушкина, {left}, офис 5")
        tables["related_persons"][0].values["address"] = (
            f"Москва, улица Пушкина, {right}, офис 5"
        )
        assert compare(tables, load_rules(ROOT / "rules.yaml")).alerts == []


def test_different_spaced_letter_suffixes_block_address_match():
    tables = single_pair(address="Москва, улица Ленина, дом 10 А, офис 5")
    tables["related_persons"][0].values["address"] = (
        "Москва, улица Ленина, дом 10 Б, офис 5"
    )
    assert compare(tables, load_rules(ROOT / "rules.yaml")).alerts == []


def test_name_requires_alphabetic_initial():
    for name in ("Сидоров -", "Сидоров 1", "Сидоров _"):
        assert (
            compare(single_pair(name=name), load_rules(ROOT / "rules.yaml")).alerts
            == []
        )


def test_different_corpus_numbers_block_address_match():
    for left, right in [("дом 10 к 2", "дом 10 к 3"), ("дом 10к2", "дом 10к3")]:
        tables = single_pair(address=f"Москва, улица Ленина, {left}, офис 5")
        tables["related_persons"][0].values["address"] = (
            f"Москва, улица Ленина, {right}, офис 5"
        )
        assert compare(tables, load_rules(ROOT / "rules.yaml")).alerts == []
