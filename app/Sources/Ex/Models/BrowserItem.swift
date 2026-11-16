import ExCore
import Foundation
import UniformTypeIdentifiers

/// Where the browser is: a folder on disk, or a folder inside an archive ("" is its root).
enum Location: Hashable {
    case folder(URL)
    case archive(URL, String)

    var archiveURL: URL? {
        if case .archive(let url, _) = self { return url }
        return nil
    }

    var innerPath: String? {
        if case .archive(_, let inner) = self { return inner }
        return nil
    }
}

/// One row of the browser, whether it lives on disk or inside an archive.
struct BrowserItem: Identifiable, Hashable {
    enum Kind: Hashable {
        case folder, archive, file
    }

    let id: String
    let name: String
    let kind: Kind
    let size: Int64?
    let packed: Int64?
    let modified: Date?
    let encrypted: Bool
    let fileCount: Int?
    /// Set for items on disk.
    let url: URL?
    /// Set for items inside an archive.
    let innerPath: String?

    var format: FormatInfo? { kind == .folder ? nil : FormatCatalog.info(forFileName: name) }
    var isFolder: Bool { kind == .folder }

    // Non-optional keys so the table can sort every column.
    var sizeKey: Int64 { size ?? -1 }
    var packedKey: Int64 { packed ?? -1 }
    var modifiedKey: Date { modified ?? .distantPast }
    var kindLabel: String {
        switch kind {
        case .folder: "Folder"
        case .archive: "\(format?.label ?? "") Archive"
        case .file:
            UTType(filenameExtension: (name as NSString).pathExtension)?.localizedDescription ?? "File"
        }
    }

    static func onDisk(_ url: URL, isDirectory: Bool, size: Int64?, modified: Date?) -> BrowserItem {
        let name = url.lastPathComponent
        let kind: Kind = isDirectory ? .folder : (FormatCatalog.isArchive(fileName: name) ? .archive : .file)
        return BrowserItem(
            id: url.path, name: name, kind: kind, size: isDirectory ? nil : size, packed: nil,
            modified: modified, encrypted: false, fileCount: nil, url: url, innerPath: nil
        )
    }

    static func inArchive(_ node: ArchiveNode) -> BrowserItem {
        let kind: Kind = node.isDir ? .folder : (FormatCatalog.isArchive(fileName: node.name) ? .archive : .file)
        return BrowserItem(
            id: node.path, name: node.name, kind: kind, size: node.size, packed: node.packed,
            modified: node.modified, encrypted: node.encrypted, fileCount: node.isDir ? node.fileCount : nil,
            url: nil, innerPath: node.path
        )
    }
}

/// A listed archive, kept so that moving around inside it is instant.
struct ArchiveSession {
    let url: URL
    let label: String
    let tree: ArchiveTree
    /// Size of the archive file(s) on disk. Solid archives do not report a
    /// packed size per entry, so this is the honest compressed total.
    let diskSize: Int64
}

enum FileSystem {
    private static let keys: [URLResourceKey] = [
        .isDirectoryKey, .isPackageKey, .fileSizeKey, .contentModificationDateKey,
    ]

    /// The visible contents of `folder`. App bundles count as files, like in Finder.
    static func items(in folder: URL) throws -> [BrowserItem] {
        let urls = try FileManager.default.contentsOfDirectory(
            at: folder, includingPropertiesForKeys: keys, options: [.skipsHiddenFiles]
        )
        return urls.map { url in
            let values = try? url.resourceValues(forKeys: Set(keys))
            let isFolder = (values?.isDirectory ?? false) && !(values?.isPackage ?? false)
            return BrowserItem.onDisk(
                url, isDirectory: isFolder,
                size: values?.fileSize.map(Int64.init), modified: values?.contentModificationDate
            )
        }
    }

    static func freeSpace(at folder: URL) -> Int64? {
        let values = try? folder.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        return values?.volumeAvailableCapacityForImportantUsage
    }

    /// Total size of files at or below `urls`, for the compress summary.
    static func totalSize(of urls: [URL]) -> Int64 {
        urls.reduce(0) { total, url in
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) else { return total }
            guard isDirectory.boolValue else {
                return total + Int64((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
            }
            let enumerator = FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.fileSizeKey])
            var sum: Int64 = 0
            while let child = enumerator?.nextObject() as? URL {
                sum += Int64((try? child.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
            }
            return total + sum
        }
    }
}
