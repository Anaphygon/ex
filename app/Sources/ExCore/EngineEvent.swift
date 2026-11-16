import Foundation

/// One entry as `ex-engine list` reports it.
public struct ArchiveEntry: Decodable, Sendable, Equatable {
    public let path: String
    public let isDir: Bool
    public let size: Int64?
    public let packed: Int64?
    public let modified: Double?
    public let encrypted: Bool

    public init(path: String, isDir: Bool, size: Int64? = nil, packed: Int64? = nil, modified: Double? = nil, encrypted: Bool = false) {
        self.path = path
        self.isDir = isDir
        self.size = size
        self.packed = packed
        self.modified = modified
        self.encrypted = encrypted
    }

    enum CodingKeys: String, CodingKey {
        case path, size, packed, modified, encrypted
        case isDir = "is_dir"
    }
}

public struct EngineResult: Sendable, Equatable {
    public let outputs: [URL]
    public let files: Int
    public let bytes: Int64
    public let notes: [String]
}

/// A line of the engine's JSON-lines protocol. See `ex/engine.py`.
public enum EngineEvent: Sendable, Equatable {
    case progress(Int?)
    case password(archive: String, retry: Bool)
    case listing(label: String, entries: [ArchiveEntry])
    case done(EngineResult)
    case formats([String])
    case error(String)
    case cancelled

    public var isTerminal: Bool {
        switch self {
        case .progress, .password: false
        default: true
        }
    }

    private struct Raw: Decodable {
        let type: String
        let percent: Int?
        let archive: String?
        let retry: Bool?
        let label: String?
        let entries: [ArchiveEntry]?
        let outputs: [String]?
        let files: Int?
        let bytes: Int64?
        let notes: [String]?
        let message: String?
        let pack: [String]?
    }

    public struct UnknownEvent: Error, Equatable {
        public let type: String
    }

    public static func decode(_ line: Data) throws -> EngineEvent {
        let raw = try JSONDecoder().decode(Raw.self, from: line)
        switch raw.type {
        case "progress":
            return .progress(raw.percent)
        case "password":
            return .password(archive: raw.archive ?? "", retry: raw.retry ?? false)
        case "listing":
            return .listing(label: raw.label ?? "?", entries: raw.entries ?? [])
        case "done":
            return .done(EngineResult(
                outputs: (raw.outputs ?? []).map { URL(fileURLWithPath: $0) },
                files: raw.files ?? 0,
                bytes: raw.bytes ?? 0,
                notes: raw.notes ?? []
            ))
        case "formats":
            return .formats(raw.pack ?? [])
        case "error":
            return .error(raw.message ?? "Failed without a message")
        case "cancelled":
            return .cancelled
        default:
            throw UnknownEvent(type: raw.type)
        }
    }
}
