# tiles-archive

Downloadable tiles for the floorpaper Flutter app.

```
tiles/<category>/<tile>.png   source images (you edit these)
thumbs/                       generated previews     -> committed
metadata.json                 generated catalogue    -> committed
dist/packs/<category>.zip     generated zips         -> NOT committed, uploaded to the "packs" Release
```

## One-time setup
1. `pip install -r tools/requirements.txt`

## Adding tiles (every time)
```bash
# 1. drop images into inbox/, then sort them into categories
python tools/tiles.py add                 # asks a category per image
python tools/tiles.py add -c floral       # or: everything goes to "floral"

# 2. check + build thumbs, metadata.json and zips
python tools/tiles.py build

# 3. upload the zips FIRST
gh release upload packs dist/packs/*.zip --clobber

# 4. then publish the catalogue
git add tiles thumbs metadata.json
git commit -m "Add tiles"
git push
```

## Rules `build` enforces
- category folders and file names: lowercase `a-z 0-9 _ -` (`add` fixes names for you)
- images: png, jpg, jpeg, webp. No sub-folders inside a category.
- ids are `<category>__<file name>`, so renaming/moving a tile creates a *new* tile.

## Removing a category
Delete its folder, run `build`, then delete the stale zip from the Release:
`gh release delete-asset packs <category>.zip`
