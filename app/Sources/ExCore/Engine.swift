import Foundation

/// Options for `ex-engine pack`; mirrors `PackOptions` in ex/pack.py.
public struct PackRequest: Sendable, Equatable {
    public var format: String
    public var level: Int
    public var password: String?
    public var encryptNames: Bool
    public var volumeBytes: Int64?

    public init(format: String, level: Int = 5, password: String? = nil, encryptNames: Bool = false, volumeBytes: Int64? = nil) {
        self.format = format
        self.level = level
        self.password = password
        self.encryptNames = encryptNames
        self.volumeBytes = volumeBytes
    }
}

extension PackRequest {
    public static func supportsPassword(_ format: String) -> Bool { ["zip", "7z", "rar"].contains(format) }
    public static func supportsHiddenNames(_ format: String) -> Bool { ["7z", "rar"].contains(format) }
    public static func supportsVolumes(_ format: String) -> Bool { ["zip", "7z", "rar"].contains(format) }

    /// This request minus options its format cannot honour, so a toggle left on
    /// for 7z does not fail a zip after the sheet has closed.
    public func sanitized() -> PackRequest {
        let password = Self.supportsPassword(format) ? password.flatMap { $0.isEmpty ? nil : $0 } : nil
        return PackRequest(
            format: format,
            level: level,
            password: password,
            encryptNames: encryptNames && password != nil && Self.supportsHiddenNames(format),
            volumeBytes: Self.supportsVolumes(format) ? volumeBytes : nil
        )
    }
}

/// Where the engine lives and how to start each command.
public struct Engine: Sendable {
    /// Inside Ex.app: Contents/Resources/engine/bin/ex-engine.
    public static let bundledPath = "engine/bin/ex-engine"
    public static let fallbackPath = "/opt/homebrew/bin/ex-engine"

    public let executable: URL

    public init(executable: URL) {
        self.executable = executable
    }

    /// `EX_ENGINE` if set, else the copy bundled in the app, else the Homebrew symlink.
    public static func locate(in bundle: Bundle = .main) -> Engine {
        let bundled = bundle.resourceURL?.appendingPathComponent(bundledPath).path
        let candidates = [ProcessInfo.processInfo.environment["EX_ENGINE"], bundled, fallbackPath].compactMap { $0 }
        let found = candidates.first { FileManager.default.isExecutableFile(atPath: $0) } ?? fallbackPath
        return Engine(executable: URL(fileURLWithPath: found))
    }

    public func list(_ archive: URL) throws -> EngineRun {
        try EngineRun(executable: executable, arguments: ["list", archive.path])
    }

    public func extract(_ archive: URL, into output: URL? = nil, only: [String] = []) throws -> EngineRun {
        var arguments = ["extract", archive.path]
        if let output { arguments += ["--output", output.path] }
        for path in only { arguments += ["--only", path] }
        return try EngineRun(executable: executable, arguments: arguments)
    }

    public func pack(_ sources: [URL], into folder: URL, name: String, request: PackRequest) throws -> EngineRun {
        var arguments = ["pack", "--format", request.format, "--name", name, "--output", folder.path, "--level", String(request.level)]
        if let volume = request.volumeBytes { arguments += ["--volume-bytes", String(volume)] }
        if request.encryptNames { arguments.append("--encrypt-names") }
        if request.password != nil { arguments.append("--password-stdin") }
        arguments.append("--")
        arguments += sources.map(\.path)
        let run = try EngineRun(executable: executable, arguments: arguments)
        if let password = request.password { run.reply(password: password) }
        return run
    }

    public func packFormats() async -> [String] {
        guard let run = try? EngineRun(executable: executable, arguments: ["formats"]) else { return [] }
        for await event in run.events {
            if case .formats(let formats) = event { return formats }
        }
        return []
    }
}
