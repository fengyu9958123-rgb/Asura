#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.qa_agents.factory import QAAgentFactory
from services.generation.image_prd_core import generate_version_prd


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ImageIntegrationAnalyst only with existing image analysis text.")
    parser.add_argument("--module-name", required=True, help="Module/version name")
    parser.add_argument("--analysis-file", required=True, help="Path to image analysis markdown/text")
    parser.add_argument("--output-dir", required=True, help="Directory to write PRD outputs")
    parser.add_argument("--images-json", help="Optional JSON file for module_info.images list")
    args = parser.parse_args()

    analysis_path = Path(args.analysis_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    image_analysis = analysis_path.read_text(encoding="utf-8")
    images = []
    if args.images_json:
        images = json.loads(Path(args.images_json).read_text(encoding="utf-8"))

    config_list_path = ROOT / "config" / "OAI_CONFIG_LIST"
    config_list = json.loads(config_list_path.read_text(encoding="utf-8"))

    factory = QAAgentFactory(config_list=config_list)
    prd_generator = factory.create_image_integration_analyst()

    modules_results = [{
        "module_info": {
            "module_name": args.module_name,
            "images": images,
        },
        "image_analysis": image_analysis,
        "success": True,
    }]

    result = generate_version_prd(
        prd_generator=prd_generator,
        version_name=args.module_name,
        modules_results=modules_results,
        output_dir=str(output_dir),
        notes_mgr=None,
        conv_logger=None,
    )
    if not result or not result.get("success"):
        print("FAILED")
        return 1
    print(result.get("prd_path") or result.get("file_path") or "OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
