from pathlib import Path
from typing import BinaryIO
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

import pandas as pd
from openpyxl.utils.exceptions import InvalidFileException

from radar.models import Diagnostic, InputError, Record, Source

COLUMNS = {
    "participants": [
        "participant_id",
        "tender_id",
        "company_name",
        "inn",
        "director_name",
        "phone",
        "email",
        "address",
    ],
    "officials": [
        "official_id",
        "full_name",
        "position",
        "role_in_tender",
        "tender_id",
    ],
    "related_persons": [
        "official_id",
        "relation_type",
        "full_name",
        "inn",
        "phone",
        "email",
        "address",
    ],
}


def _records(
    frame: pd.DataFrame, role: str, filename: str, sheet: str | None
) -> list[Record]:
    if frame.empty:
        raise InputError(
            [
                Diagnostic(
                    code="missing_headers",
                    file_role=role,
                    message="Нет строки заголовков",
                )
            ]
        )
    headers = [str(value).strip() for value in frame.iloc[0]]
    errors = []
    for column in COLUMNS[role]:
        if headers.count(column) != 1:
            errors.append(
                Diagnostic(
                    code="invalid_header",
                    file_role=role,
                    field=column,
                    message=f"Заголовок {column} должен встречаться ровно один раз",
                )
            )
    if errors:
        raise InputError(errors)
    positions = {column: headers.index(column) for column in COLUMNS[role]}
    result = []
    for row, values in enumerate(frame.itertuples(index=False, name=None), start=1):
        if row == 1 or not any(str(value).strip() for value in values):
            continue
        result.append(
            Record(
                {column: str(values[index]) for column, index in positions.items()},
                Source(file_role=role, filename=filename, sheet=sheet, row=row),
            )
        )
    return result


def read_excel(file: BinaryIO, role: str, filename: str) -> list[Record]:
    try:
        with pd.ExcelFile(file, engine="openpyxl") as workbook:
            sheets = [
                (
                    name,
                    pd.read_excel(
                        workbook,
                        sheet_name=name,
                        header=None,
                        dtype=str,
                        keep_default_na=False,
                    ),
                )
                for name in workbook.sheet_names
            ]
        populated = [
            (name, frame)
            for name, frame in sheets
            if not frame.empty
            and frame.apply(lambda col: col.astype(str).str.strip().ne("")).any().any()
        ]
        if len(populated) != 1:
            raise InputError(
                [
                    Diagnostic(
                        code="ambiguous_sheet",
                        file_role=role,
                        message="Требуется ровно один лист данных",
                    )
                ]
            )
        name, frame = populated[0]
        return _records(frame, role, filename, name)
    except (
        BadZipFile,
        InvalidFileException,
        ParseError,
        ValueError,
        KeyError,
        IndexError,
        OSError,
    ) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError(
            [
                Diagnostic(
                    code="invalid_workbook",
                    file_role=role,
                    message="Не удалось прочитать книгу XLSX",
                )
            ]
        ) from exc


def read_csv(path: Path, role: str) -> list[Record]:
    frame = pd.read_csv(
        path, sep=";", encoding="utf-8", header=None, dtype=str, keep_default_na=False
    )
    return _records(frame, role, path.name, None)
