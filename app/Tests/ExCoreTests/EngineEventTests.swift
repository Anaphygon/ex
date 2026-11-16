import Foundation
import Testing
@testable import ExCore

@Suite struct EngineEventTests {
    func decode(_ json: String) throws -> EngineEvent {
        try EngineEvent.decode(Data(json.utf8))
    }

    @Test func progressWithAndWithoutPercent() throws {
        #expect(try decode(#"{"type":"progress","percent":42}"#) == .progress(42))
        #expect(try decode(#"{"type":"progress","percent":null}"#) == .progress(nil))
    }

    @Test func passwordRequest() throws {
        #expect(try decode(#"{"type":"password","archive":"e.7z","retry":true}"#) == .password(archive: "e.7z", retry: true))
    }

    @Test func listing() throws {
        let event = try decode(#"{"type":"listing","label":"rar5","entries":[{"path":"a/b","is_dir":false,"size":3,"packed":null,"modified":1.5,"encrypted":true}]}"#)
        #expect(event == .listing(label: "rar5", entries: [ArchiveEntry(path: "a/b", isDir: false, size: 3, modified: 1.5, encrypted: true)]))
    }

    @Test func done() throws {
        let event = try decode(#"{"type":"done","outputs":["/tmp/x"],"files":2,"bytes":10,"seconds":0.1,"notes":["n"]}"#)
        #expect(event == .done(EngineResult(outputs: [URL(fileURLWithPath: "/tmp/x")], files: 2, bytes: 10, notes: ["n"])))
    }

    @Test func terminalEvents() throws {
        #expect(try decode(#"{"type":"error","message":"boom"}"#).isTerminal)
        #expect(try decode(#"{"type":"cancelled"}"#).isTerminal)
        #expect(!(try decode(#"{"type":"progress","percent":1}"#).isTerminal))
    }

    @Test func unknownTypeThrows() {
        #expect(throws: EngineEvent.UnknownEvent.self) { try decode(#"{"type":"mystery"}"#) }
    }
}
