#!/usr/bin/env python3
"""
tiles.py - helper for the floorpaper-tiles content repo.

  python tools/tiles.py add [--category NAME]   sort images from inbox/ into tiles/<category>/
  python tools/tiles.py build [--force]         check everything, then generate:
                                                  thumbs/*.webp    (committed)
                                                  metadata.json    (committed)
                                                  dist/packs/*.zip (NOT committed, upload to a Release)

Layout:  tiles/<category>/<tile>.png   <- the only thing you ever edit by hand
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

# ---------------------------------------------------------------------------
# EDIT THESE TWO LINES after you create the GitHub repo
# ---------------------------------------------------------------------------
GITHUB_USER = "abelgeorgeantony"
GITHUB_REPO = "tiles-archive"
# ---------------------------------------------------------------------------

BRANCH = "main"
RELEASE_TAG = "packs"  # the Release that holds the zips
BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{BRANCH}/"
PACKS_BASE_URL = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/releases/download/{RELEASE_TAG}/"

ROOT = Path(__file__).resolve().parent.parent
TILES_DIR = ROOT / "tiles"
INBOX_DIR = ROOT / "inbox"
THUMBS_DIR = ROOT / "thumbs"
DIST_DIR = ROOT / "dist" / "packs"
METADATA = ROOT / "metadata.json"

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
THUMB_MAX = 256
SCHEMA_VERSION = 1
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


# ---------------------------------------------------------------- helpers ---

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return text or "tile"


def pretty(slug: str) -> str:
    return re.sub(r"[_-]+", " ", slug).strip().title()


def list_categories() -> list[Path]:
    if not TILES_DIR.is_dir():
        return []
    return sorted(p for p in TILES_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in EXTENSIONS)


# -------------------------------------------------------------------- add ---

def cmd_add(args) -> int:
    INBOX_DIR.mkdir(exist_ok=True)
    images = list_images(INBOX_DIR)
    if not images:
        print(f"Nothing to do: {INBOX_DIR} has no images.")
        return 0

    # content hash -> existing path, so the same image is never added twice
    known = {sha256_of(p): p for cat in list_categories() for p in list_images(cat)}

    fixed_category = slugify(args.category) if args.category else None
    added = 0

    for src in images:
        digest = sha256_of(src)
        if digest in known:
            print(f"skip  {src.name}: identical to {known[digest].relative_to(ROOT)}")
            continue

        category = fixed_category or ask_category(src)
        if category is None:
            print(f"skip  {src.name}")
            continue

        dest_dir = TILES_DIR / category
        dest_dir.mkdir(parents=True, exist_ok=True)

        base = slugify(src.stem)
        dest = dest_dir / f"{base}{src.suffix.lower()}"
        n = 2
        while dest.exists():
            dest = dest_dir / f"{base}_{n}{src.suffix.lower()}"
            n += 1

        shutil.move(str(src), dest)
        known[digest] = dest
        added += 1
        print(f"added {dest.relative_to(ROOT)}")

    print(f"\n{added} image(s) added. Next: python tools/tiles.py build")
    return 0


def ask_category(src: Path) -> str | None:
    cats = [c.name for c in list_categories()]
    print(f"\n{src.name}")
    for i, name in enumerate(cats, 1):
        print(f"  {i}) {name}")
    while True:
        answer = input("  number, or type a new category name (Enter = skip): ").strip()
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(cats):
            return cats[int(answer) - 1]
        if not answer.isdigit():
            return slugify(answer)
        print("  not a valid number")


# ------------------------------------------------------------------ build ---

def make_thumbnail(src: Path, dest: Path) -> None:
    with Image.open(src) as img:
        has_alpha = "A" in img.getbands() or img.mode == "P"
        img = img.convert("RGBA" if has_alpha else "RGB")
        img.thumbnail((THUMB_MAX, THUMB_MAX))
        img.save(dest, "WEBP", quality=80)


def make_pack(zip_path: Path, files: list[Path]) -> None:
    """Deterministic zip: same input files -> byte-identical zip on any machine.

    Images are already compressed, so entries are STORED (no deflate). That also
    removes any dependence on the zlib version, and the app unpacks it faster.
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for f in sorted(files, key=lambda p: p.name):
            info = zipfile.ZipInfo(f.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            zf.writestr(info, f.read_bytes())


def cmd_build(args) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    categories = list_categories()
    if not categories:
        print(f"No categories found in {TILES_DIR}. Run 'add' first.")
        return 1

    old = {}
    if METADATA.exists():
        try:
            old = {t["id"]: t for t in json.loads(METADATA.read_text())["tiles"]}
        except (ValueError, KeyError):
            old = {}

    THUMBS_DIR.mkdir(exist_ok=True)
    tiles, cat_entries = [], []
    seen_hashes: dict[str, str] = {}
    wanted_thumbs: set[str] = set()

    for cat in categories:
        if not SLUG_RE.match(cat.name):
            errors.append(f"category folder '{cat.name}' must be lowercase a-z, 0-9, _ or -")

        for stray in sorted(cat.iterdir()):
            if stray.is_dir():
                errors.append(f"{stray.relative_to(ROOT)}: sub-folders are not supported")
            elif stray.suffix.lower() not in EXTENSIONS and stray.name != ".gitkeep":
                warnings.append(f"{stray.relative_to(ROOT)}: ignored (not an image)")

        files = list_images(cat)
        if not files:
            warnings.append(f"category '{cat.name}' is empty and will be skipped")
            continue

        cat_tiles = []
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            if not SLUG_RE.match(f.stem):
                errors.append(f"{rel}: file name must be lowercase a-z, 0-9, _ or - (try 'add')")
                continue

            digest = sha256_of(f)
            if digest in seen_hashes:
                warnings.append(f"{rel} is identical to {seen_hashes[digest]}")
            seen_hashes.setdefault(digest, rel)

            try:
                with Image.open(f) as img:
                    width, height = img.size
            except Exception as e:  # any decode problem is a user error
                errors.append(f"{rel}: cannot read image ({e})")
                continue

            # The id includes the category, so it never depends on what other tiles exist.
            tile_id = f"{cat.name}__{f.stem}"
            thumb_name = f"{tile_id}.webp"
            thumb_path = THUMBS_DIR / thumb_name
            wanted_thumbs.add(thumb_name)

            unchanged = old.get(tile_id, {}).get("sha256") == digest
            if args.force or not unchanged or not thumb_path.exists():
                make_thumbnail(f, thumb_path)

            cat_tiles.append({
                "id": tile_id,
                "name": pretty(f.stem),
                "category": cat.name,
                "file": rel,
                "thumbnail": f"thumbs/{thumb_name}",
                "width": width,
                "height": height,
                "sizeBytes": f.stat().st_size,
                "sha256": digest,
            })

        if not cat_tiles:
            continue

        pack_file = f"{cat.name}.zip"
        pack_path = DIST_DIR / pack_file
        make_pack(pack_path, [ROOT / t["file"] for t in cat_tiles])
        tiles.extend(cat_tiles)
        cat_entries.append({
            "id": cat.name,
            "name": pretty(cat.name),
            "count": len(cat_tiles),
            "pack": {
                "file": pack_file,
                "sizeBytes": pack_path.stat().st_size,
                "sha256": sha256_of(pack_path),
            },
        })

    for w in warnings:
        print(f"warning: {w}")
    if errors:
        for e in errors:
            print(f"ERROR:   {e}")
        print("\nFix the errors above and run build again. metadata.json was not touched.")
        return 1

    # remove thumbnails and zips whose tile/category no longer exists
    for t in THUMBS_DIR.glob("*.webp"):
        if t.name not in wanted_thumbs:
            t.unlink()
    wanted_zips = {c["pack"]["file"] for c in cat_entries}
    for z in DIST_DIR.glob("*.zip"):
        if z.name not in wanted_zips:
            z.unlink()

    metadata = {
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": "",
        "baseUrl": BASE_URL,
        "packsBaseUrl": PACKS_BASE_URL,
        "categories": cat_entries,
        "tiles": tiles,
    }

    # Keep the old timestamp when nothing changed, so git shows no pointless diff.
    previous = None
    if METADATA.exists():
        try:
            previous = json.loads(METADATA.read_text())
        except ValueError:
            pass
    if previous and {**previous, "updatedAt": ""} == metadata:
        metadata["updatedAt"] = previous["updatedAt"]
    else:
        metadata["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    METADATA.write_text(json.dumps(metadata, indent=2) + "\n")

    print(f"\nOK: {len(tiles)} tiles, {len(cat_entries)} categories (one zip each).")
    print(f"Zips are in {DIST_DIR.relative_to(ROOT)}/ - upload them to the '{RELEASE_TAG}' release,")
    print("then commit and push thumbs/ and metadata.json (see README).")
    return 0


# ------------------------------------------------------------------- main ---

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="sort images from inbox/ into categories")
    p_add.add_argument("-c", "--category", help="put every inbox image in this category (no questions)")
    p_add.set_defaults(func=cmd_add)

    p_build = sub.add_parser("build", help="validate, then make thumbnails, metadata.json and zips")
    p_build.add_argument("--force", action="store_true", help="regenerate all thumbnails")
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
