from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from assemble_return import assemble_artifacts, write_artifacts  # noqa: E402
from normalize_docs import normalize_payload  # noqa: E402
from tax_flow_common import dump_json, ensure_dir, load_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the shared tax flow from raw input to output artifacts.")
    parser.add_argument("--input", required=True, type=Path, help="Raw input JSON payload.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output directory.")
    args = parser.parse_args()

    raw_payload = load_json(args.input)
    normalized = normalize_payload(raw_payload)

    ensure_dir(args.out_dir)
    normalized_path = args.out_dir / "normalized.json"
    dump_json(normalized_path, normalized)

    artifacts = assemble_artifacts(normalized)
    write_artifacts(args.out_dir, artifacts)


if __name__ == "__main__":
    main()

