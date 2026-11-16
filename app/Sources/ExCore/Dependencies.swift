import Foundation

/// The free command-line tools the engine runs on, all from Homebrew.
public enum Dependencies {
    public struct Tool: Sendable, Equatable {
        public let binary: String
        public let formula: String
    }

    public static let required: [Tool] = [
        Tool(binary: "python3", formula: "python"),
        Tool(binary: "7zz", formula: "sevenzip"),
        Tool(binary: "unar", formula: "unar"),
    ]

    /// The engine's launcher names this interpreter, so it must be exactly here.
    public static let searchFolders = ["/opt/homebrew/bin"]

    public static func missing(in folders: [String] = searchFolders) -> [Tool] {
        required.filter { tool in
            !folders.contains { FileManager.default.isExecutableFile(atPath: "\($0)/\(tool.binary)") }
        }
    }

    public static func installCommand(for tools: [Tool]) -> String {
        "brew install " + tools.map(\.formula).joined(separator: " ")
    }
}
