from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / ".agents/skills/tax-avoidance/scripts/run_tax_flow.py"
FIXTURES = REPO_ROOT / "tests/fixtures/cases.json"
EXAMPLE_INPUT = REPO_ROOT / "examples/contractor-and-investment-input.json"


class TaxFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with FIXTURES.open("r", encoding="utf-8") as handle:
            cls.cases = json.load(handle)

    def run_case(self, name: str) -> tuple[dict, dict[str, str]]:
        case = self.cases[name]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.json"
            out_dir = temp_path / "out"
            input_path.write_text(json.dumps(case["input"], indent=2), encoding="utf-8")

            subprocess.run(
                ["uv", "run", "python", str(RUNNER), "--input", str(input_path), "--out-dir", str(out_dir)],
                check=True,
                cwd=REPO_ROOT,
            )

            normalized = json.loads((out_dir / "return-data.json").read_text(encoding="utf-8"))
            text_artifacts = {
                "tax-dossier.md": (out_dir / "tax-dossier.md").read_text(encoding="utf-8"),
                "federal-lines.md": (out_dir / "federal-lines.md").read_text(encoding="utf-8"),
                "missing-items.md": (out_dir / "missing-items.md").read_text(encoding="utf-8"),
            }

            for required in ("tax-dossier.md", "return-data.json", "federal-lines.md", "missing-items.md"):
                self.assertTrue((out_dir / required).exists(), f"{required} was not created for {name}")
            return normalized, text_artifacts

    def test_happy_paths(self) -> None:
        for name in (
            "w2_single",
            "mfj_common_deductions",
            "investment_household",
            "education_credit_household",
            "schedule_c_contractor",
            "duplicate_doc_sources",
        ):
            with self.subTest(name=name):
                normalized, artifacts = self.run_case(name)
                self.assertEqual(normalized["status"], self.cases[name]["expect"]["status"])
                expected = self.cases[name]["expect"]
                federal_lines = artifacts["federal-lines.md"]
                if "line_1a" in expected:
                    self.assertIn(f"${expected['line_1a']:,.2f}", federal_lines)
                if "line_2b" in expected:
                    self.assertIn(f"${expected['line_2b']:,.2f}", federal_lines)
                if "line_3b" in expected:
                    self.assertIn(f"${expected['line_3b']:,.2f}", federal_lines)
                if "line_20" in expected:
                    self.assertIn(f"${expected['line_20']:,.2f}", federal_lines)
                if "line_25a" in expected:
                    self.assertIn(f"${expected['line_25a']:,.2f}", federal_lines)
                if "schedule_c_line_1" in expected:
                    self.assertIn(f"${expected['schedule_c_line_1']:,.2f}", federal_lines)
                if "schedule_c_line_31" in expected:
                    self.assertIn(f"${expected['schedule_c_line_31']:,.2f}", federal_lines)

    def test_connector_upload_fallback(self) -> None:
        normalized, artifacts = self.run_case("connector_upload_fallback")
        self.assertEqual(normalized["status"], "ok")
        notes = "\n".join(normalized["connector_notes"])
        self.assertIn("Upload fallback is active", notes)
        self.assertIn("upload://upload-w2", artifacts["tax-dossier.md"])

    def test_unsupported_cases(self) -> None:
        for name in ("unsupported_complex_equity",):
            with self.subTest(name=name):
                normalized, artifacts = self.run_case(name)
                self.assertEqual(normalized["status"], "unsupported")
                self.assertIn("Unsupported", artifacts["missing-items.md"])

    def test_supported_but_incomplete_cases(self) -> None:
        for name in (
            "metadata_only_tax_docs",
            "schedule_c_missing_expenses",
            "unsupported_schedule_c",
            "education_credit_1098t_review",
        ):
            with self.subTest(name=name):
                normalized, artifacts = self.run_case(name)
                self.assertEqual(normalized["status"], "ok")
                self.assertIn("Missing Items", artifacts["missing-items.md"])

    def test_education_credit_1098t_review(self) -> None:
        normalized, artifacts = self.run_case("education_credit_1098t_review")
        self.assertEqual(normalized["status"], "ok")
        self.assertEqual(normalized["facts"]["qualified_tuition"]["value"], 12500)
        self.assertEqual(normalized["facts"]["scholarships_grants"]["value"], 4000)
        self.assertIn("Education Credit Review", artifacts["tax-dossier.md"])
        self.assertIn("$12,500.00", artifacts["tax-dossier.md"])
        self.assertIn("$4,000.00", artifacts["tax-dossier.md"])
        self.assertIn("A 1098-T was found.", artifacts["missing-items.md"])

    def test_candidate_business_expenses(self) -> None:
        normalized, artifacts = self.run_case("schedule_c_candidate_expenses")
        self.assertEqual(normalized["status"], "ok")
        self.assertIn("$371.89", artifacts["tax-dossier.md"])
        self.assertIn("candidate business-expense receipts", artifacts["missing-items.md"])
        self.assertIn("Anthropic", artifacts["tax-dossier.md"])
        self.assertIn("AI tools", artifacts["tax-dossier.md"])

    def test_expense_year_filter(self) -> None:
        normalized, artifacts = self.run_case("expense_year_filter")
        self.assertEqual(normalized["status"], "ok")
        self.assertIn("$48.00", artifacts["tax-dossier.md"])
        self.assertIn("candidate business-expense receipts totaling $48.00", artifacts["missing-items.md"])

    def test_state_follow_up(self) -> None:
        normalized, artifacts = self.run_case("state_follow_up")
        self.assertEqual(normalized["status"], "ok")
        self.assertIn("State Follow-Up", artifacts["tax-dossier.md"])
        self.assertIn("California state return support is planned but not yet automated.", artifacts["tax-dossier.md"])
        self.assertIn("Multiple work states are present.", artifacts["missing-items.md"])

    def test_state_allocations(self) -> None:
        normalized, artifacts = self.run_case("state_allocations")
        self.assertEqual(normalized["status"], "ok")
        self.assertIn("State Wages", artifacts["tax-dossier.md"])
        self.assertIn("$73,000.00", artifacts["tax-dossier.md"])
        self.assertIn("$650.00", artifacts["tax-dossier.md"])

    def test_illegal_request(self) -> None:
        normalized, artifacts = self.run_case("illegal_request")
        self.assertEqual(normalized["status"], "refused")
        self.assertTrue(normalized["illegal_reasons"])
        self.assertIn("Refusal", artifacts["missing-items.md"])
        self.assertIn("tax evasion", artifacts["tax-dossier.md"])

    def test_example_input_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "out"
            subprocess.run(
                ["uv", "run", "python", str(RUNNER), "--input", str(EXAMPLE_INPUT), "--out-dir", str(out_dir)],
                check=True,
                cwd=REPO_ROOT,
            )
            dossier = (out_dir / "tax-dossier.md").read_text(encoding="utf-8")
            self.assertIn("Candidate Business Expenses", dossier)
            self.assertIn("$48,000.00", dossier)


if __name__ == "__main__":
    unittest.main()
