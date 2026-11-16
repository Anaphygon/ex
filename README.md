# Ex

An archive manager for macOS in the spirit of WinRAR and ZArchiver. Browse into archives like folders, pull out a single file or everything, and make new archives. There's also an `ex` command and a Finder "Extract Here" action.

```
$ ex dataset.rar

  dataset.rar  rar5  412 MB
  ✓ ./dataset/  23 files, 1.2 GB  4.1s
```

## Install

### The app (DMG)

1. Install the free tools Ex works with, using [Homebrew](https://brew.sh):
   ```
   brew install python sevenzip unar
   ```
2. Download `Ex-<version>.dmg` from [Releases](../../releases) and drag **Ex** into Applications.
3. Open it once with right-click → **Open**. Ex is not notarized by Apple, so macOS asks first. If it says the app is damaged, run `xattr -dr com.apple.quarantine /Applications/Ex.app`.

Apple Silicon Macs on macOS 26 or later.

### Everything, from source

Gets the app, the `ex` command, and the Finder Quick Action. Needs Command Line Tools (`xcode-select --install`); Xcode is not required.

```
git clone https://github.com/Anaphygon/ex.git
cd ex
./install.sh               # install or update
./install.sh --uninstall   # remove everything it added
```

The installer links `/opt/homebrew/bin/ex-extract` and `ex-engine`, adds one alias line to `~/.zshrc`, installs the Quick Action in `~/Library/Services`, and builds `~/Applications/Ex.app`.

The command is really `ex-extract`, because `/usr/bin/ex` is the system's vi editor. The `ex` alias only applies to interactive shells, so scripts that call the real `ex` keep working.

## Using the app

- **Browse like Finder.** Archives open like folders, with sizes, packed sizes, and search.
- **Extract all or some.** Select files inside an archive, then Extract Here (⌘E) or Extract To… (⌥⌘E).
- **Drag files out** of an archive straight into Finder.
- **Space** for Quick Look. **Double-click** opens a file inside an archive, including archives inside archives.
- **Compress (⌘K)** to zip, 7z, rar, tar.gz, tar.xz or tar.zst, with a password, hidden file names, and splitting into 100 MB to 4 GB volumes.
- **Drop files on the window.** Archives open, anything else is offered for compressing.
- **Task queue** with progress bars. Cancelling leaves nothing behind.
- A password is asked for once per archive while the app is open.

Double-clicking a `.rar` or `.zst` opens Ex. `.zip` stays with Archive Utility unless you choose Open With → Ex.

## Terminal and Finder

| From | How |
|---|---|
| Terminal | `ex file.rar`, `ex *.zip`, or `ex -o ~/somewhere file.7z` |
| Terminal, no file names | `ex` scans the current folder and asks first |
| Finder | Right-click an archive → Quick Actions → **Extract Here** |

## What it does for you

- **Detects formats by content**, not by name.
- **Tidy results.** An archive holding one folder gives you that folder; loose files get a folder named after the archive.
- **Never overwrites.** Name taken? The result becomes `name (2)`. The archive itself is never touched.
- **No half-finished mess.** Work happens in a hidden folder that only appears when complete.
- **Split archives** from any part: `.part1.rar`, `.7z.001`, `.zip.001`, `.z01`.
- **Legacy file names**, such as Japanese zips from Windows, decode correctly.
- **macOS clutter is dropped**: `__MACOSX` and `.DS_Store`.

## Formats

zip, 7z, rar (4 and 5), tar, gz, bz2, xz, zst, lz4, br, lzma, Z, iso, dmg, cab, lzh, arj, cpio, ar/deb, rpm, xar/pkg, wim, msi, chm, vhd, squashfs, sit, alz, zoo, self-extracting exe, plus jar/apk/docx when named directly. Anything else is still tried with `7zz` and `unar`.

## Security

Archives from the internet are treated as untrusted:

- Entries like `../../evil` stay inside the result folder.
- Symlinks pointing outside the archive are removed, and reported.
- The macOS quarantine flag is copied onto extracted files, so an app inside a downloaded zip still goes through Gatekeeper, as with Archive Utility.

Passwords are passed to `7zz`, `rar` and `lsar` as arguments, so they are visible in the process list (`ps`) while those run. Keep that in mind on a shared Mac.

## Project layout

| Path | Contents |
|---|---|
| `ex/` | Python engine: format detection, extract, list, compress |
| `ex/engine.py` | JSON-lines protocol the app drives (`ex-engine list/extract/pack`) |
| `app/` | SwiftUI app: `ExCore` (archive tree, protocol) and `Ex` (UI) |
| `integration/` | Finder Quick Action, icon, app Info.plist |

## Building and testing

```
uv run pytest --cov                  # engine
app/test.sh --package-path app       # app, including tests against the real engine
app/make-dmg.sh                      # release build → app/build/Ex-<version>.dmg
```
