#!/usr/bin/env python3
"""
Builds the single self-contained index.html by embedding every stream
listed in streams/manifest.json into viewer/template.html.

For each manifest entry {id, label, video, data}, reads that stream's
data.json (mosaic_width, mosaic_height, samples) and merges it with the
manifest fields into one object. The full list replaces the STREAMS
placeholder in viewer/template.html.

index.html is written at the project root (same folder as the videos) so
its relative <video src="..."> paths keep working.

Usage (from the project root):
    python3 scripts/package.py
    python3 scripts/package.py --out dist/index.html   # custom output path
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)

PLACEHOLDER_RE = re.compile(
    r"(// ===== EMBEDDED_STREAMS_DATA_PLACEHOLDER =====\n)"
    r".*?\n"
    r"(// ===== END_EMBEDDED_STREAMS_DATA_PLACEHOLDER =====)",
    re.DOTALL,
)


def build_streams_array(project_root):
    manifest_path = os.path.join(project_root, "streams", "manifest.json")
    if not os.path.isfile(manifest_path):
        raise SystemExit(
            f"no streams/manifest.json found at {manifest_path} -- "
            f"run pipeline/build_stream.py for at least one video first"
        )
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    streams = []
    for entry in manifest["streams"]:
        data_path = os.path.join(project_root, entry["data"])
        if not os.path.isfile(data_path):
            raise SystemExit(f"manifest references missing data file: {data_path}")
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)

        # detections.json is optional -- streams without one just get an empty list
        detections_path = os.path.join(os.path.dirname(data_path), "detections.json")
        detections = []
        if os.path.isfile(detections_path):
            with open(detections_path, encoding="utf-8") as f:
                det_data = json.load(f)
            detections = det_data.get("detections", [])

        streams.append({
            "id": entry["id"],
            "label": entry["label"],
            "video": entry["video"],
            "mosaic_width": data["mosaic_width"],
            "mosaic_height": data["mosaic_height"],
            "samples": data["samples"],
            "detections": detections,
        })
    if not streams:
        raise SystemExit("streams/manifest.json has no entries -- nothing to package")
    return streams


def package(project_root=".", template_path=None, out_path=None):
    project_root = os.path.abspath(project_root)
    template_path = template_path or os.path.join(project_root, "viewer", "template.html")
    out_path = out_path or os.path.join(project_root, "index.html")

    streams = build_streams_array(project_root)
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    streams_json = json.dumps(streams, ensure_ascii=False, separators=(",", ":"))
    replacement = r"\1const STREAMS = " + streams_json.replace("\\", "\\\\") + r";\n\2"
    new_html, n = PLACEHOLDER_RE.subn(replacement, template)
    if n != 1:
        raise SystemExit(
            "could not find the STREAMS placeholder markers in "
            f"{template_path} (expected exactly 1 match, found {n}) -- "
            "has the template been edited in a way that broke the markers?"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(new_html)

    labels = ", ".join(f"{s['id']} ({s['label']})" for s in streams)
    print(f"wrote {out_path}  [{len(streams)} stream(s): {labels}]", file=sys.stderr)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", default=DEFAULT_ROOT)
    ap.add_argument("--template", default=None, help="override viewer/template.html path")
    ap.add_argument("--out", default=None, help="override output path (default: <project-root>/index.html)")
    args = ap.parse_args()
    package(project_root=args.project_root, template_path=args.template, out_path=args.out)


if __name__ == "__main__":
    main()
