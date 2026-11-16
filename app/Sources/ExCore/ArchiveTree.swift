import Foundation

/// A file or folder inside an archive. Folders carry the totals of everything below them.
public struct ArchiveNode: Sendable, Identifiable, Equatable {
    public let path: String
    public let name: String
    public let isDir: Bool
    public let size: Int64?
    public let packed: Int64?
    public let modified: Date?
    public let encrypted: Bool
    public let fileCount: Int
    public let children: [ArchiveNode]

    public var id: String { path }
}

/// The flat entry list an engine reports, turned into folders you can walk.
///
/// Archives often omit folder entries (`a/b.txt` with no `a/`), and some list
/// a path twice; both are normal and handled here.
public struct ArchiveTree: Sendable {
    public let root: ArchiveNode
    private let index: [String: ArchiveNode]

    public init(entries: [ArchiveEntry]) {
        let builder = Builder()
        for entry in entries {
            builder.add(entry)
        }
        root = builder.freeze(path: "", name: "")
        var index: [String: ArchiveNode] = [:]
        Self.collect(root, into: &index)
        self.index = index
    }

    public func node(at path: String) -> ArchiveNode? {
        index[path]
    }

    public var fileCount: Int { root.fileCount }
    public var totalSize: Int64 { root.size ?? 0 }
    public var packedSize: Int64? { root.packed }
    public var hasEncryptedEntries: Bool { index.values.contains { $0.encrypted && !$0.isDir } }

    private static func collect(_ node: ArchiveNode, into index: inout [String: ArchiveNode]) {
        index[node.path] = node
        for child in node.children {
            collect(child, into: &index)
        }
    }

    /// Mutable scaffolding used only while building; the tree itself is immutable.
    private final class Builder {
        var isDir = true
        var entry: ArchiveEntry?
        var children: [String: Builder] = [:]

        func add(_ entry: ArchiveEntry) {
            let parts = entry.path.split(separator: "/").map(String.init)
            guard !parts.isEmpty else { return }
            var node = self
            for part in parts.dropLast() {
                node = node.child(part)
                node.isDir = true
            }
            let leaf = node.child(parts[parts.count - 1])
            leaf.isDir = entry.isDir || !leaf.children.isEmpty
            leaf.entry = entry
        }

        private func child(_ name: String) -> Builder {
            if let existing = children[name] { return existing }
            let created = Builder()
            created.isDir = false
            children[name] = created
            return created
        }

        func freeze(path: String, name: String) -> ArchiveNode {
            let frozen = children
                .map { childName, child in
                    child.freeze(path: path.isEmpty ? childName : "\(path)/\(childName)", name: childName)
                }
                .sorted { lhs, rhs in
                    if lhs.isDir != rhs.isDir { return lhs.isDir }
                    return lhs.name.localizedStandardCompare(rhs.name) == .orderedAscending
                }
            guard isDir else {
                return ArchiveNode(
                    path: path, name: name, isDir: false,
                    size: entry?.size, packed: entry?.packed,
                    modified: entry?.modified.map { Date(timeIntervalSince1970: $0) },
                    encrypted: entry?.encrypted ?? false, fileCount: 1, children: []
                )
            }
            let packedValues = frozen.map(\.packed)
            return ArchiveNode(
                path: path, name: name, isDir: true,
                size: frozen.reduce(0) { $0 + ($1.size ?? 0) },
                packed: packedValues.contains(nil) ? nil : packedValues.reduce(0) { $0 + ($1 ?? 0) },
                modified: entry?.modified.map { Date(timeIntervalSince1970: $0) } ?? frozen.compactMap(\.modified).max(),
                encrypted: frozen.contains { $0.encrypted },
                fileCount: frozen.reduce(0) { $0 + $1.fileCount },
                children: frozen
            )
        }
    }
}
