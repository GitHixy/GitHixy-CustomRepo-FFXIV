"""Builds repo.json from the latest GitHub release of every plugin in plugins.json.

Each plugin release must carry a `latest.zip` asset made by DalamudPackager; the
manifest inside it is the source of truth for name, version and description.
"""

import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSET_NAME = "latest.zip"
TOKEN = os.environ.get("GITHUB_TOKEN")


def fetch(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "GitHixy-CustomRepo"})
    if TOKEN and url.startswith("https://api.github.com"):
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req) as res:
        return res.read()


def find_asset(release):
    return next((a for a in release["assets"] if a["name"] == ASSET_NAME), None)


def read_manifest(asset, internal_name=None):
    with zipfile.ZipFile(io.BytesIO(fetch(asset["browser_download_url"], "application/octet-stream"))) as zf:
        names = [n for n in zf.namelist() if n.endswith(".json") and not n.endswith(".deps.json") and "/" not in n and "\\" not in n]
        if internal_name:
            names = [n for n in names if n == f"{internal_name}.json"] or names
        return json.loads(zf.read(names[0]).decode("utf-8-sig"))


def unix_time(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def build_entry(plugin):
    repo = plugin["repo"]
    releases = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases?per_page=50"))
    releases = [r for r in releases if not r["draft"] and find_asset(r)]
    stable = next((r for r in releases if not r["prerelease"]), None)
    testing = next((r for r in releases if r["prerelease"]), None)
    if testing and stable and unix_time(testing["published_at"]) < unix_time(stable["published_at"]):
        testing = None
    if not stable and not testing:
        print(f"  {repo}: no release with {ASSET_NAME}, skipped")
        return None

    main = stable or testing
    entry = read_manifest(find_asset(main))
    stable_url = find_asset(stable)["browser_download_url"] if stable else None
    testing_url = find_asset(testing)["browser_download_url"] if testing else stable_url

    entry.update({
        "IconUrl": f"https://raw.githubusercontent.com/{repo}/main/icon.png",
        "RepoUrl": entry.get("RepoUrl") or f"https://github.com/{repo}",
        "DownloadLinkInstall": stable_url or testing_url,
        "DownloadLinkUpdate": stable_url or testing_url,
        "DownloadLinkTesting": testing_url,
        "DownloadCount": sum(find_asset(r)["download_count"] for r in releases),
        "LastUpdate": unix_time(main["published_at"]),
        "CategoryTags": plugin.get("categoryTags", []),
        "IsHide": False,
        "IsTestingExclusive": stable is None,
    })
    if testing:
        entry["TestingAssemblyVersion"] = read_manifest(find_asset(testing), entry["InternalName"])["AssemblyVersion"]

    print(f"  {repo}: {entry['AssemblyVersion']}" + (f" (testing {entry['TestingAssemblyVersion']})" if testing else ""))
    return entry


def main():
    plugins = json.loads((ROOT / "plugins.json").read_text(encoding="utf-8"))
    previous = {e.get("RepoUrl", "").lower(): e for e in json.loads((ROOT / "repo.json").read_text(encoding="utf-8"))}
    entries = []
    for plugin in plugins:
        try:
            entry = build_entry(plugin)
        except Exception as e:
            # A failed lookup keeps the plugin's last known entry instead of dropping it from the repo.
            print(f"  {plugin['repo']}: FAILED - {e}", file=sys.stderr)
            entry = previous.get(f"https://github.com/{plugin['repo']}".lower())
        if entry:
            entries.append(entry)

    out = json.dumps(entries, indent=2, ensure_ascii=False) + "\n"
    (ROOT / "repo.json").write_text(out, encoding="utf-8", newline="\n")
    print(f"repo.json: {len(entries)} plugin(s)")


if __name__ == "__main__":
    main()
