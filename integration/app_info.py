"""Write the Info.plist of Ex.app.

Declaring the archive types matters beyond "Open With": macOS has no idea
.rar or .zst are archives until some app says so, and the Quick Action only
shows up for files that conform to public.archive.

Usage: app_info.py OUTPUT_PLIST VERSION
"""

import plistlib
import sys
from pathlib import Path

BUNDLE_ID = "id.lisvindanu.ex"
MINIMUM_MACOS = "26.0"

# identifier, description, extensions
UNDECLARED_ARCHIVE_TYPES = (
    ("com.rarlab.rar-archive", "RAR Archive", ("rar",)),
    ("org.tukaani.xz-archive", "XZ Archive", ("xz", "txz")),
    ("com.facebook.zstandard-archive", "Zstandard Archive", ("zst", "tzst")),
    ("org.lz4.lz4-archive", "LZ4 Archive", ("lz4",)),
    ("org.nongnu.lzip-archive", "Lzip Archive", ("lz",)),
    ("org.tukaani.lzma-archive", "LZMA Archive", ("lzma",)),
    ("com.microsoft.cab-archive", "Cabinet Archive", ("cab",)),
    ("id.lisvindanu.ex.lzh-archive", "LZH Archive", ("lzh", "lha")),
    ("id.lisvindanu.ex.arj-archive", "ARJ Archive", ("arj",)),
    ("id.lisvindanu.ex.alz-archive", "ALZ Archive", ("alz",)),
    ("id.lisvindanu.ex.zoo-archive", "Zoo Archive", ("zoo",)),
    ("id.lisvindanu.ex.split-volume", "Split Archive Volume", ("001",)),
)


def imported_types() -> list[dict]:
    return [
        {
            "UTTypeIdentifier": identifier,
            "UTTypeDescription": description,
            "UTTypeConformsTo": ["public.archive", "public.data"],
            "UTTypeTagSpecification": {"public.filename-extension": list(extensions)},
        }
        for identifier, description, extensions in UNDECLARED_ARCHIVE_TYPES
    ]


def document_types() -> list[dict]:
    # "Alternate" means Archive Utility keeps .zip by default, while formats
    # nothing else on the Mac can open (.rar, .zst) fall to this app.
    return [
        {
            "CFBundleTypeName": "Archive",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["public.archive", "public.disk-image"],
        },
        {
            "CFBundleTypeName": "Folder",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "None",
            "LSItemContentTypes": ["public.folder"],
        },
    ]


def info(version: str) -> dict:
    return {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": "Ex",
        "CFBundleDisplayName": "Ex",
        "CFBundleExecutable": "Ex",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "CFBundleIconFile": "Ex",
        "CFBundleDevelopmentRegion": "en",
        "LSMinimumSystemVersion": MINIMUM_MACOS,
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticTermination": False,
        "CFBundleDocumentTypes": document_types(),
        "UTImportedTypeDeclarations": imported_types(),
    }


if __name__ == "__main__":
    output, version = sys.argv[1:3]
    Path(output).write_bytes(plistlib.dumps(info(version)))
