import Foundation
import Testing
@testable import ExCore

@Suite struct DependenciesTests {
    @Test func everythingIsMissingFromAnEmptyFolder() throws {
        let empty = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: empty, withIntermediateDirectories: true)
        let missing = Dependencies.missing(in: [empty.path])
        #expect(missing.map(\.binary) == ["python3", "7zz", "unar"])
        #expect(Dependencies.installCommand(for: missing) == "brew install python sevenzip unar")
    }

    @Test func thisMachineHasEverything() {
        #expect(Dependencies.missing().isEmpty)
    }
}
