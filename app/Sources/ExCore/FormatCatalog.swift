import Foundation

public enum FormatFamily: String, Sendable, CaseIterable {
    case zip, sevenZip, rar, tar, disk, other
}

public struct FormatInfo: Sendable, Equatable {
    public let label: String
    public let family: FormatFamily

    public init(label: String, family: FormatFamily) {
        self.label = label
        self.family = family
    }
}

/// Recognises archives by name, for icons and for deciding what a double-click does.
///
/// The engine detects formats by content; this is only the cheap first guess
/// a file browser needs for thousands of rows.
public enum FormatCatalog {
    private static let suffixes: [(String, FormatInfo)] = [
        (".tar.gz", FormatInfo(label: "TAR.GZ", family: .tar)),
        (".tar.xz", FormatInfo(label: "TAR.XZ", family: .tar)),
        (".tar.zst", FormatInfo(label: "TAR.ZST", family: .tar)),
        (".tar.bz2", FormatInfo(label: "TAR.BZ2", family: .tar)),
        (".tar.lz4", FormatInfo(label: "TAR.LZ4", family: .tar)),
        (".tgz", FormatInfo(label: "TGZ", family: .tar)),
        (".txz", FormatInfo(label: "TXZ", family: .tar)),
        (".tbz2", FormatInfo(label: "TBZ2", family: .tar)),
        (".tar", FormatInfo(label: "TAR", family: .tar)),
        (".zip", FormatInfo(label: "ZIP", family: .zip)),
        (".zipx", FormatInfo(label: "ZIPX", family: .zip)),
        (".apk", FormatInfo(label: "APK", family: .zip)),
        (".ipa", FormatInfo(label: "IPA", family: .zip)),
        (".jar", FormatInfo(label: "JAR", family: .zip)),
        (".whl", FormatInfo(label: "WHL", family: .zip)),
        (".7z", FormatInfo(label: "7Z", family: .sevenZip)),
        (".rar", FormatInfo(label: "RAR", family: .rar)),
        (".gz", FormatInfo(label: "GZ", family: .tar)),
        (".bz2", FormatInfo(label: "BZ2", family: .tar)),
        (".xz", FormatInfo(label: "XZ", family: .tar)),
        (".zst", FormatInfo(label: "ZST", family: .tar)),
        (".lz4", FormatInfo(label: "LZ4", family: .tar)),
        (".lzma", FormatInfo(label: "LZMA", family: .tar)),
        (".iso", FormatInfo(label: "ISO", family: .disk)),
        (".dmg", FormatInfo(label: "DMG", family: .disk)),
        (".wim", FormatInfo(label: "WIM", family: .disk)),
        (".vhd", FormatInfo(label: "VHD", family: .disk)),
        (".vhdx", FormatInfo(label: "VHDX", family: .disk)),
        (".cab", FormatInfo(label: "CAB", family: .other)),
        (".lzh", FormatInfo(label: "LZH", family: .other)),
        (".lha", FormatInfo(label: "LHA", family: .other)),
        (".arj", FormatInfo(label: "ARJ", family: .other)),
        (".cpio", FormatInfo(label: "CPIO", family: .other)),
        (".deb", FormatInfo(label: "DEB", family: .other)),
        (".rpm", FormatInfo(label: "RPM", family: .other)),
        (".sit", FormatInfo(label: "SIT", family: .other)),
        (".sitx", FormatInfo(label: "SITX", family: .other)),
        (".alz", FormatInfo(label: "ALZ", family: .other)),
    ]

    /// The format of `fileName`, including split volumes like `x.7z.001` and `x.part2.rar`.
    public static func info(forFileName fileName: String) -> FormatInfo? {
        let lowered = fileName.lowercased()
        // Regex literals are not Sendable, so they cannot be shared statics.
        if lowered.firstMatch(of: /\.part\d+\.rar$/) != nil {
            return FormatInfo(label: "RAR", family: .rar)
        }
        if let match = lowered.wholeMatch(of: /^(.+?)\.(\d{3})$/) {
            return info(forFileName: String(match.1))
        }
        return suffixes.first { lowered.hasSuffix($0.0) && lowered.count > $0.0.count }?.1
    }

    public static func isArchive(fileName: String) -> Bool {
        info(forFileName: fileName) != nil
    }
}
