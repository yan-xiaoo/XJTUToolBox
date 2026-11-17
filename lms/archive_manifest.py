"""Local manifests for the existing LMS batch downloader (no network code)."""
import datetime
import json
import os
import tempfile
from pathlib import Path


class ArchiveManifest:
    def __init__(self, target_dir, course_name, activities):
        self.root = Path(tempfile.mkdtemp(prefix="LMS归档_", dir=target_dir))
        self.path = self.root / "manifest.json"
        self.data = {
            "version": 1, "course": course_name,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "running",
            "activities": [{"id": a.get("id"), "title": a.get("title"),
                            "type": a.get("type")} for a in activities],
            "files": [], "collection_failures": [],
        }
        self.save()

    def save(self):
        # Neither signed download URLs nor account credentials belong in an archive.
        fd, name = tempfile.mkstemp(prefix=".manifest-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def add(self, path, label):
        row = {"path": Path(path).relative_to(self.root).as_posix(),
               "label": label, "status": "pending"}
        self.data["files"].append(row)
        return row

    def finish(self, status):
        self.data["status"] = status
        for row in self.data["files"]:
            if row["status"] == "pending":
                row["status"] = "cancelled" if status == "cancelled" else "not_downloaded"
        self.save()
