"""READ-ONLY COM oracle for the real 1C 818HA reference clone (evidence class NATIVE_COM_QUERY).

* Connects to the RO clone with the disposable-copy administrator whose secret is a DPAPI CurrentUser blob.
* Only runs queries whose text starts with ВЫБРАТЬ (SELECT); a guard rejects anything else. It never calls
  Записать / Удалить / Провести.  Data never leaves the process except as counts / hashes / aggregates.
* Comparison-only evidence: it can never validate a semantic profile (see scripts/real1c/evidence.py).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

CLONE = Path("D:/ERP_MCP_Testbed/1c/reference/working/818HA_test_ready")
SECRETS = Path("D:/secrets/erp_mcp")

KINDS = ("Catalogs", "Documents", "AccumulationRegisters", "AccountingRegisters", "InformationRegisters",
         "ChartsOfAccounts")
QUERY_KIND = {
    "Catalogs": "Справочник", "Documents": "Документ", "AccumulationRegisters": "РегистрНакопления",
    "AccountingRegisters": "РегистрБухгалтерии", "InformationRegisters": "РегистрСведений",
    "ChartsOfAccounts": "ПланСчетов",
}


def dec(value) -> Decimal:
    """Exact two-decimal Decimal from a COM number (None/NULL -> 0)."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


class OracleReadOnlyViolation(PermissionError):
    pass


class Oracle:
    def __init__(self, base: Path | str = CLONE):
        import win32com.client
        import win32crypt

        user_file = SECRETS / "admin_1c_clone_user.txt"
        user = user_file.read_text(encoding="utf-8").strip() if user_file.exists() else "Admin_1C"
        blob = (SECRETS / "admin_1c_clone_password.dpapi").read_bytes()
        password = win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-8")
        self.conn = win32com.client.Dispatch("V83.COMConnector").Connect(
            f'File="{base}";Usr="{user}";Pwd="{password}";')

    # ---- guarded query ----
    def query(self, text: str):
        if not text.lstrip().upper().startswith("ВЫБРАТЬ"):
            raise OracleReadOnlyViolation("oracle is read-only: only ВЫБРАТЬ queries are allowed")
        q = self.conn.NewObject("Запрос", text)
        return q.Выполнить().Выгрузить()

    def rows(self, text: str, fields: tuple[str, ...]) -> list[dict]:
        table = self.query(text)
        out = []
        for i in range(table.Count()):
            row = table.Get(i)
            out.append({f: getattr(row, f) for f in fields})
        return out

    def scalar(self, text: str, field: str = "К"):
        table = self.query(text)
        return getattr(table.Get(0), field) if table.Count() else None

    def count(self, kind: str, name: str, where: str = "") -> int:
        return int(self.scalar(f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ {QUERY_KIND[kind]}.{name} КАК Т {where}"))

    def guid(self, ref) -> str:
        return str(self.conn.String(ref.УникальныйИдентификатор()))

    # ---- identity / structure ----
    def platform_and_config(self) -> dict:
        md = self.conn.Metadata
        return {
            "platform_version": str(self.conn.NewObject("СистемнаяИнформация").ВерсияПриложения),
            "configuration_name": str(md.Name),
            "configuration_version": str(md.Version),
            "configuration_synonym": str(md.Synonym),
        }

    def metadata_names(self) -> list[str]:
        return sorted(f"{kind}.{obj.Name}" for kind in KINDS for obj in getattr(self.conn.Metadata, kind))

    def table_counts(self) -> dict[str, int]:
        return {f"{kind}.{obj.Name}": self.count(kind, obj.Name)
                for kind in KINDS for obj in getattr(self.conn.Metadata, kind)}

    def fingerprint(self) -> dict:
        names = self.metadata_names()
        counts = self.table_counts()
        lines = [f"{key}={counts[key]}" for key in sorted(counts)]
        return {
            "metadata_fingerprint": hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest(),
            "metadata_object_count": len(names),
            "content_fingerprint_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
            "table_count": len(counts),
            "total_rows": sum(counts.values()),
            "nonempty_tables": sum(1 for value in counts.values() if value),
            "per_table": counts,
        }

    def organisations(self) -> list[dict]:
        rows = self.rows("ВЫБРАТЬ Т.Ссылка КАК Ссылка, Т.Наименование КАК Наименование, "
                         "Т.ПометкаУдаления КАК Пм ИЗ Справочник.Организации КАК Т",
                         ("Ссылка", "Наименование", "Пм"))
        return [{"ref": self.guid(r["Ссылка"]), "name": str(r["Наименование"]), "deletion_mark": bool(r["Пм"])}
                for r in rows]
