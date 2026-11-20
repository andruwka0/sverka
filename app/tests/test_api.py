from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from radar.main import create_app
from radar.tables import COLUMNS
from tests.test_check import ROOT, demo


def files(tables=None):
    tables = tables or demo()
    result = {}
    for role, records in tables.items():
        book = Workbook()
        book.active.append(COLUMNS[role])
        for record in records:
            book.active.append([record.values[col] for col in COLUMNS[role]])
        buffer = BytesIO()
        book.save(buffer)
        result[role] = (
            f"{role}.xlsx",
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return result


def test_http_returns_demo_alert():
    with TestClient(create_app(ROOT / "rules.yaml")) as client:
        response = client.post("/api/v1/checks", files=files())
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["alert_count"] == 1
    assert data["alerts"][0]["score"] == 80
    assert data["alerts"][0]["sources"][0]["row"] == 3


def test_missing_corrupt_and_missing_header_have_uniform_errors():
    with TestClient(create_app(ROOT / "rules.yaml")) as client:
        missing = files()
        del missing["officials"]
        response = client.post("/api/v1/checks", files=missing)
        assert response.status_code == 422
        assert response.json()["errors"][0]["file_role"] == "officials"
        corrupt = files()
        corrupt["participants"] = ("bad.xlsx", b"not a workbook")
        response = client.post("/api/v1/checks", files=corrupt)
        assert response.status_code == 422
        assert response.json()["errors"][0]["code"] == "invalid_workbook"
        incomplete = files()
        book = Workbook()
        book.active.append([c for c in COLUMNS["participants"] if c != "phone"])
        buffer = BytesIO()
        book.save(buffer)
        incomplete["participants"] = ("bad.xlsx", buffer.getvalue())
        response = client.post("/api/v1/checks", files=incomplete)
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "phone"


def test_duplicate_keys_are_rejected_with_row_numbers():
    from copy import deepcopy

    tables = demo()
    tables["participants"].append(deepcopy(tables["participants"][1]))
    with TestClient(create_app(ROOT / "rules.yaml")) as client:
        response = client.post("/api/v1/checks", files=files(tables))
    assert response.status_code == 422
    assert response.json()["errors"][0]["rows"] == [3, 5]


def test_blank_rows_preserve_physical_excel_row_numbers():
    data = files()
    from openpyxl import load_workbook

    book = load_workbook(BytesIO(data["participants"][1]))
    book.active.insert_rows(2)
    buffer = BytesIO()
    book.save(buffer)
    data["participants"] = ("shifted.xlsx", buffer.getvalue())
    with TestClient(create_app(ROOT / "rules.yaml")) as client:
        response = client.post("/api/v1/checks", files=data)
    assert response.status_code == 200
    assert response.json()["alerts"][0]["sources"][0]["row"] == 4
    assert response.json()["summary"]["rows_read"]["participants"] == 3


def test_multiple_populated_sheets_are_rejected():
    from openpyxl import load_workbook

    data = files()
    book = load_workbook(BytesIO(data["participants"][1]))
    book.create_sheet("second").append(["data"])
    buffer = BytesIO()
    book.save(buffer)
    data["participants"] = ("ambiguous.xlsx", buffer.getvalue())
    with TestClient(create_app(ROOT / "rules.yaml")) as client:
        response = client.post("/api/v1/checks", files=data)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "ambiguous_sheet"


def test_invalid_configuration_prevents_startup(tmp_path):
    import pytest

    config = tmp_path / "bad.yaml"
    config.write_text("rules: []\nalert_levels: {}")
    with (
        pytest.raises(ValueError, match="Invalid rules configuration"),
        TestClient(create_app(config)),
    ):
        pass


def test_broken_shared_string_reference_returns_422():
    import re
    from zipfile import ZipFile

    data = files()
    output = BytesIO()
    with (
        ZipFile(BytesIO(data["participants"][1])) as source,
        ZipFile(output, "w") as target,
    ):
        for name in source.namelist():
            content = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                content = re.sub(
                    rb'<c r="A1".*?</c>', b'<c r="A1" t="s"><v>99999</v></c>', content
                )
            target.writestr(name, content)
    data["participants"] = ("broken.xlsx", output.getvalue())
    with TestClient(
        create_app(ROOT / "rules.yaml"), raise_server_exceptions=False
    ) as client:
        response = client.post("/api/v1/checks", files=data)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "invalid_workbook"


def test_frontend_is_served_alongside_api():
    with TestClient(create_app(ROOT / "rules.yaml")) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Сверка связей" in response.text
        assert client.get("/app.js").status_code == 200
        assert client.post("/api/v1/checks").status_code == 422
