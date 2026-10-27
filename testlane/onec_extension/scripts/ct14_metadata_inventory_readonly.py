"""Print metadata-only inventory for the guarded CT14 disposable clone.

This command reads the configuration/document metadata needed to prepare a reviewed COM crosswalk.
It does not query business rows, inspect or change effective rights, create 1C objects, or write files.
Credentials are loaded by the existing clone-only DPAPI helper and never emitted.
"""
from __future__ import annotations

import gc
import json
import sys
from pathlib import Path
from typing import Any

from ct14_common import CLONE_PATH, admin_creds, connect


DOCUMENT_NAME = "ПоступлениеТоваровУслуг"


def _metadata_names(collection: Any) -> list[str]:
    names = []
    for item in collection:
        name = item.Имя
        if type(name) is not str or not name:
            raise ValueError("CT14_METADATA_SHAPE_INVALID")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("CT14_METADATA_SHAPE_INVALID")
    return sorted(names)


def _inventory(connection: Any) -> dict[str, object]:
    metadata = connection.Метаданные
    document = metadata.Документы.Найти(DOCUMENT_NAME)
    if document is None:
        raise ValueError("CT14_DOCUMENT_METADATA_MISSING")
    sections = []
    for section in document.ТабличныеЧасти:
        section_name = section.Имя
        if type(section_name) is not str or not section_name:
            raise ValueError("CT14_METADATA_SHAPE_INVALID")
        sections.append({
            "name": section_name,
            "attributes": _metadata_names(section.Реквизиты),
        })
    if len({item["name"] for item in sections}) != len(sections):
        raise ValueError("CT14_METADATA_SHAPE_INVALID")
    return {
        "clone": Path(CLONE_PATH).name,
        "platform_version": str(connection.NewObject("СистемнаяИнформация").ВерсияПриложения),
        "configuration": {
            "name": str(metadata.Name),
            "version": str(metadata.Version),
        },
        "document": DOCUMENT_NAME,
        "document_attributes": _metadata_names(document.Реквизиты),
        "tabular_sections": sorted(sections, key=lambda item: item["name"]),
    }


def main() -> int:
    initialized = False
    connection = None
    result = None
    error_code = "CT14_METADATA_COM_INIT_FAILED"
    exception_type = None
    hresult = None
    automation_codes = None
    diagnostic_class = None
    user = ""
    password = ""
    try:
        import pythoncom

        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        initialized = True
        error_code = "CT14_METADATA_CREDENTIALS_UNAVAILABLE"
        user, password = admin_creds()
        error_code = "CT14_METADATA_COM_CONNECT_FAILED"
        connection = connect(user, password)  # ct14_common enforces the exact 818HA_p2diff path.
        password = ""
        user = ""
        error_code = "CT14_METADATA_READ_FAILED"
        result = _inventory(connection)
    except Exception as exc:
        exception_type = type(exc).__name__
        value = getattr(exc, "hresult", None)
        if type(value) is int:
            hresult = f"0x{value & 0xffffffff:08X}"
        info = getattr(exc, "excepinfo", None)
        if type(info) is tuple and len(info) > 5:
            automation_codes = [
                f"0x{item & 0xffffffff:08X}" if type(item) is int else None
                for item in (info[0], info[5])
            ]
            description = info[2]
            if type(description) is str:
                normalized = description.casefold()
                if "license" in normalized or "лиценз" in normalized:
                    diagnostic_class = "LICENSE"
                elif ("password" in normalized or "парол" in normalized
                      or "authentication" in normalized or "аутентификац" in normalized):
                    diagnostic_class = "AUTHENTICATION"
                elif ("file" in normalized or "файл" in normalized
                      or "database" in normalized or "баз" in normalized):
                    diagnostic_class = "BASE_OR_DATABASE"
                else:
                    diagnostic_class = "UNCLASSIFIED"
    finally:
        connection = None
        password = ""
        user = ""
        gc.collect()
        if initialized:
            pythoncom.CoUninitialize()
    if result is None:
        failure = {"error": error_code}
        if exception_type is not None:
            failure["exception_type"] = exception_type
        if hresult is not None:
            failure["hresult"] = hresult
        if automation_codes is not None:
            failure["automation_codes"] = automation_codes
        if diagnostic_class is not None:
            failure["diagnostic_class"] = diagnostic_class
        print(json.dumps(failure))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
