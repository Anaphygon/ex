import AppKit
import ExCore
import Foundation
import Observation

struct PasswordPrompt: Identifiable {
    let id = UUID()
    let run: ObjectIdentifier
    let archiveName: String
    let retry: Bool
    let respond: @MainActor (String?) -> Void
}

struct AlertMessage: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}

/// Settings for one "compress" sheet.
struct CompressDraft: Identifiable {
    let id = UUID()
    var sources: [URL]
    var folder: URL
    var name: String
    var format = "zip"
    var level = 5
    var password = ""
    var confirmation = ""
    var encryptNames = false
    var volumeBytes: Int64?
}

/// Everything the window shows. One per app: Ex has a single browser window.
@MainActor @Observable final class AppModel {
    static let shared = AppModel()

    let engine = Engine.locate()
    let tasks = TaskCenter()

    // Browser state
    var location: Location
    var items: [BrowserItem] = []
    var selection: Set<BrowserItem.ID> = []
    var sortOrder = [KeyPathComparator(\BrowserItem.name, comparator: .localizedStandard)]
    var search = ""
    var busyMessage: String?
    var backStack: [Location] = []
    var forwardStack: [Location] = []
    var sessions: [URL: ArchiveSession] = [:]
    var recentArchives: [URL] = []

    // Presentation
    var passwordPrompt: PasswordPrompt?
    var compressDraft: CompressDraft?
    var alert: AlertMessage?
    var previewURL: URL?
    var packFormats = ["zip", "7z", "tar.gz", "tar.xz", "tar.zst", "tar"]

    @ObservationIgnored private var promptQueue: [PasswordPrompt] = []
    @ObservationIgnored private var knownPasswords: [String: String] = [:]
    @ObservationIgnored let cacheFolder: URL

    static let recentLimit = 8
    private static let recentKey = "recentArchives"
    private static let lastFolderKey = "lastFolder"

    private init() {
        let defaults = UserDefaults.standard
        let downloads = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let saved = defaults.string(forKey: Self.lastFolderKey).map { URL(fileURLWithPath: $0) }
        let start = saved.flatMap { FileManager.default.fileExists(atPath: $0.path) ? $0 : nil } ?? downloads
        location = .folder(start)
        recentArchives = (defaults.stringArray(forKey: Self.recentKey) ?? [])
            .map { URL(fileURLWithPath: $0) }
            .filter { FileManager.default.fileExists(atPath: $0.path) }
        cacheFolder = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("id.lisvindanu.ex/open", isDirectory: true)
        try? FileManager.default.removeItem(at: cacheFolder)
        tasks.onPassword = { [weak self] archive, retry, run in
            self?.answerPassword(for: archive, retry: retry, run: run)
        }
        tasks.onRunEnded = { [weak self] run in self?.withdrawPrompts(for: run) }
        reload()
        let missing = Dependencies.missing()
        if !missing.isEmpty {
            show(
                error: "Ex extracts with a few free tools from Homebrew. Install them in Terminal:\n\n"
                    + Dependencies.installCommand(for: missing),
                title: "Almost ready"
            )
        }
        Task { packFormats = await engine.packFormats().nonEmpty ?? packFormats }
    }

    // MARK: Passwords

    /// Answers an engine's password request: from memory first, then by asking.
    func answerPassword(for archive: URL, retry: Bool, run: EngineRun) {
        if !retry, let known = knownPasswords[archive.path] {
            run.reply(password: known)
            return
        }
        let prompt = PasswordPrompt(run: ObjectIdentifier(run), archiveName: archive.lastPathComponent, retry: retry) { [weak self] answer in
            if let answer { self?.knownPasswords[archive.path] = answer }
            run.reply(password: answer)
            self?.showNextPrompt()
        }
        promptQueue.append(prompt)
        if passwordPrompt == nil { showNextPrompt() }
    }

    func knownPassword(for archive: URL) -> String? {
        knownPasswords[archive.path]
    }

    /// Drops prompts of a run that has ended, e.g. one cancelled while asking.
    func withdrawPrompts(for run: EngineRun) {
        let id = ObjectIdentifier(run)
        promptQueue.removeAll { $0.run == id }
        if passwordPrompt?.run == id { showNextPrompt() }
    }

    private func showNextPrompt() {
        passwordPrompt = promptQueue.isEmpty ? nil : promptQueue.removeFirst()
    }

    // MARK: Remembered places

    func rememberArchive(_ url: URL) {
        recentArchives.removeAll { $0 == url }
        recentArchives.insert(url, at: 0)
        recentArchives = Array(recentArchives.prefix(Self.recentLimit))
        UserDefaults.standard.set(recentArchives.map(\.path), forKey: Self.recentKey)
    }

    func rememberFolder(_ url: URL) {
        UserDefaults.standard.set(url.path, forKey: Self.lastFolderKey)
    }

    func show(error message: String, title: String = "Something went wrong") {
        alert = AlertMessage(title: title, message: message)
    }
}

extension Array {
    var nonEmpty: Self? { isEmpty ? nil : self }
}
