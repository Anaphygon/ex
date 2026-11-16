import Foundation

/// One running engine command: its events, password replies, and cancel.
///
/// The stream always finishes with a terminal event, even if the engine
/// itself dies without printing one.
public final class EngineRun: @unchecked Sendable {
    public let events: AsyncStream<EngineEvent>

    private let process = Process()
    private let input = Pipe()
    private let output = Pipe()
    private let lock = NSLock()
    private var inputOpen = true

    public init(executable: URL, arguments: [String]) throws {
        let (stream, continuation) = AsyncStream<EngineEvent>.makeStream()
        events = stream
        process.executableURL = executable
        process.arguments = arguments
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        let reader = output.fileHandleForReading
        let process = process
        try process.run()
        Task.detached {
            var finished = false
            do {
                for try await line in reader.bytes.lines {
                    guard let event = try? EngineEvent.decode(Data(line.utf8)) else { continue }
                    continuation.yield(event)
                    finished = finished || event.isTerminal
                }
            } catch {
                // The pipe closing is the normal end; the exit status decides below.
            }
            process.waitUntilExit()
            if !finished {
                continuation.yield(.error("The ex engine stopped unexpectedly (code \(process.terminationStatus))"))
            }
            continuation.finish()
        }
    }

    /// Answers a `password` event; nil cancels the prompt.
    public func reply(password: String?) {
        let message: [String: Any] = password.map { ["password": $0] } ?? ["cancel": true]
        guard var line = try? JSONSerialization.data(withJSONObject: message) else { return }
        line.append(0x0A)
        lock.withLock {
            guard inputOpen else { return }
            try? input.fileHandleForWriting.write(contentsOf: line)
        }
    }

    /// Stops the work; the engine cleans up and ends with `cancelled`.
    ///
    /// The signal goes first: closing stdin first would make an engine that is
    /// waiting for a password read EOF and report "password needed" instead.
    public func cancel() {
        if process.isRunning {
            process.terminate()
        }
        lock.withLock { inputOpen = false }
    }
}
