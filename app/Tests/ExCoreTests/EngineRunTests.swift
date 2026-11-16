import Foundation
import Testing
@testable import ExCore

/// Drives the real engine from the repository, so the Swift side and the
/// protocol cannot drift apart unnoticed.
@Suite(.serialized) struct EngineRunTests {
    let engine = Engine(executable: URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().appendingPathComponent("bin/ex-engine"))

    func scratch() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("ex-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    func makeArchive(in folder: URL, password: String? = nil) async throws -> URL {
        let source = folder.appendingPathComponent("payload")
        try FileManager.default.createDirectory(at: source.appendingPathComponent("sub"), withIntermediateDirectories: true)
        try "alpha".write(to: source.appendingPathComponent("a.txt"), atomically: true, encoding: .utf8)
        try "beta".write(to: source.appendingPathComponent("sub/b.txt"), atomically: true, encoding: .utf8)
        let run = try engine.pack([source], into: folder, name: "bundle", request: PackRequest(format: "7z", password: password, encryptNames: password != nil))
        for await event in run.events {
            if case .done(let result) = event { return result.outputs[0] }
        }
        throw CocoaError(.fileWriteUnknown)
    }

    @Test func listsWhatItPacked() async throws {
        let archive = try await makeArchive(in: scratch())
        var entries: [ArchiveEntry] = []
        for await event in try engine.list(archive).events {
            if case .listing(_, let found) = event { entries = found }
        }
        let tree = ArchiveTree(entries: entries)
        #expect(tree.node(at: "payload/sub/b.txt")?.size == 4)
    }

    @Test func extractsASelection() async throws {
        let folder = try scratch()
        let archive = try await makeArchive(in: folder)
        let target = folder.appendingPathComponent("picked")
        var outputs: [URL] = []
        for await event in try engine.extract(archive, into: target, only: ["payload/sub/b.txt"]).events {
            if case .done(let result) = event { outputs = result.outputs }
        }
        #expect(outputs.map(\.lastPathComponent) == ["b.txt"])
    }

    @Test func answersPasswordPrompts() async throws {
        let archive = try await makeArchive(in: scratch(), password: "secret")
        let run = try engine.list(archive)
        var asked: [Bool] = []
        var listed = false
        for await event in run.events {
            switch event {
            case .password(_, let retry):
                asked.append(retry)
                run.reply(password: retry ? "secret" : "wrong")
            case .listing:
                listed = true
            default:
                break
            }
        }
        #expect(asked == [false, true] && listed)
    }

    @Test func cancellingAPromptEndsWithAnError() async throws {
        let archive = try await makeArchive(in: scratch(), password: "secret")
        let run = try engine.list(archive)
        var last: EngineEvent?
        for await event in run.events {
            if case .password = event { run.reply(password: nil) }
            last = event
        }
        guard case .error = last else {
            Issue.record("expected error, got \(String(describing: last))")
            return
        }
    }

    @Test func cancellingWhileAskingForAPasswordEndsAsCancelled() async throws {
        let archive = try await makeArchive(in: scratch(), password: "secret")
        let run = try engine.extract(archive)
        var last: EngineEvent?
        for await event in run.events {
            if case .password = event { run.cancel() }
            last = event
        }
        #expect(last == .cancelled)
    }

    @Test func sanitizedRequestsDropWhatTheFormatCannotDo() {
        let zip = PackRequest(format: "zip", password: "p", encryptNames: true, volumeBytes: 10).sanitized()
        #expect(zip.password == "p" && !zip.encryptNames && zip.volumeBytes == 10)
        let tar = PackRequest(format: "tar.gz", password: "p", encryptNames: true, volumeBytes: 10).sanitized()
        #expect(tar.password == nil && !tar.encryptNames && tar.volumeBytes == nil)
        let sevenZip = PackRequest(format: "7z", password: "", encryptNames: true).sanitized()
        #expect(sevenZip.password == nil && !sevenZip.encryptNames)
        #expect(PackRequest(format: "7z", password: "p", encryptNames: true).sanitized().encryptNames)
    }

    @Test func aMissingEngineFailsToStart() {
        #expect(throws: (any Error).self) {
            try EngineRun(executable: URL(fileURLWithPath: "/nonexistent/ex-engine"), arguments: [])
        }
    }

    @Test func aDyingEngineStillEndsTheStream() async throws {
        let run = try EngineRun(executable: URL(fileURLWithPath: "/bin/sh"), arguments: ["-c", "exit 3"])
        var events: [EngineEvent] = []
        for await event in run.events { events.append(event) }
        #expect(events.count == 1)
        guard case .error = events.first else {
            Issue.record("expected error")
            return
        }
    }

    @Test func packFormatsAreReported() async {
        #expect(await engine.packFormats().contains("zip"))
    }
}
