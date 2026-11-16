import AppKit
import ExCore
import Foundation
import UniformTypeIdentifiers

extension AppModel {
    // MARK: Opening

    /// Double-click or Return: go into folders and archives, open files.
    func open(_ ids: Set<BrowserItem.ID>) {
        let chosen = items.filter { ids.contains($0.id) }
        guard chosen.count == 1, let item = chosen.first else {
            chosen.compactMap(\.url).forEach { NSWorkspace.shared.open($0) }
            return
        }
        switch (item.kind, location) {
        case (.folder, .folder):
            if let url = item.url { go(to: .folder(url)) }
        case (.folder, .archive(let archive, _)):
            go(to: .archive(archive, item.innerPath ?? ""))
        case (.archive, .folder):
            if let url = item.url { openArchive(url) }
        case (.file, .folder):
            if let url = item.url { NSWorkspace.shared.open(url) }
        case (_, .archive):
            withLocalCopy(of: item) { [weak self] url in
                if item.kind == .archive { self?.openArchive(url) } else { NSWorkspace.shared.open(url) }
            }
        }
    }

    /// Space bar: Quick Look, extracting archive entries to a private cache first.
    func previewSelection() {
        guard let item = selectedItems.first, !item.isFolder else { return }
        if let url = item.url {
            previewURL = url
        } else {
            withLocalCopy(of: item) { [weak self] url in self?.previewURL = url }
        }
    }

    /// Extracts one entry of the current archive to the cache and hands back its path.
    func withLocalCopy(of item: BrowserItem, then use: @escaping @MainActor (URL) -> Void) {
        guard let archive = location.archiveURL, let inner = item.innerPath else { return }
        let folder = cacheFolder.appendingPathComponent(UUID().uuidString, isDirectory: true)
        startExtraction(.open, of: archive, into: folder, only: [inner], title: "Opening \(item.name)") { result in
            if let first = result.outputs.first { use(first) }
        }
    }

    func items(for ids: Set<BrowserItem.ID>) -> [BrowserItem] {
        items.filter { ids.contains($0.id) }
    }

    func revealInFinder(_ picked: [BrowserItem]? = nil) {
        let urls = (picked ?? selectedItems).compactMap(\.url)
        NSWorkspace.shared.activateFileViewerSelecting(urls.isEmpty ? [workingFolder] : urls)
    }

    // MARK: Extracting

    var canExtract: Bool { canExtract(selectedItems) }

    func canExtract(_ picked: [BrowserItem]) -> Bool {
        location.archiveURL != nil || picked.contains { $0.kind == .archive }
    }

    /// Inside an archive: the given items (the selection by default), or
    /// everything when there are none. On disk: the given archives.
    func extract(_ chosen: [BrowserItem]? = nil, into destination: URL? = nil) {
        let chosen = chosen ?? selectedItems
        switch location {
        case .archive(let archive, _):
            let picked = chosen.compactMap(\.innerPath)
            let target = destination ?? archive.deletingLastPathComponent()
            let title = picked.isEmpty ? "Extract \(archive.lastPathComponent)" : "Extract \(picked.count) items"
            startExtraction(.extract, of: archive, into: picked.isEmpty ? destination : target, only: picked, title: title) { [weak self] _ in
                self?.reload()
            }
        case .folder:
            for item in chosen where item.kind == .archive {
                guard let url = item.url else { continue }
                startExtraction(.extract, of: url, into: destination, only: [], title: "Extract \(item.name)") { [weak self] result in
                    self?.reload(selecting: result.outputs.map(\.lastPathComponent))
                }
            }
        }
    }

    func extractAll(into destination: URL? = nil) {
        guard let archive = location.archiveURL else { return }
        startExtraction(.extract, of: archive, into: destination, only: [], title: "Extract \(archive.lastPathComponent)") { _ in }
    }

    func chooseDestination(then extract: @escaping @MainActor (URL) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Extract Here"
        panel.directoryURL = workingFolder
        guard panel.runModal() == .OK, let url = panel.url else { return }
        extract(url)
    }

    func startExtraction(
        _ kind: TaskItem.Kind,
        of archive: URL,
        into destination: URL?,
        only: [String],
        title: String,
        onSuccess: @escaping @MainActor (EngineResult) -> Void
    ) {
        do {
            let run = try engine.extract(archive, into: destination, only: only)
            tasks.start(kind, title: title, archive: archive, run: run, onSuccess: onSuccess)
        } catch {
            show(error: "Could not start the ex engine: \(error.localizedDescription)")
        }
    }

    // MARK: Compressing

    var canCompress: Bool { canCompress(selectedItems) }

    func canCompress(_ picked: [BrowserItem]) -> Bool {
        currentFolder != nil && !picked.isEmpty
    }

    func beginCompress(_ urls: [URL]? = nil) {
        let sources = urls ?? selectedItems.compactMap(\.url)
        guard let first = sources.first else { return }
        let folder = urls == nil ? workingFolder : first.deletingLastPathComponent()
        let name = sources.count == 1
            ? first.deletingPathExtension().lastPathComponent
            : folder.lastPathComponent
        compressDraft = CompressDraft(sources: sources, folder: folder, name: name)
    }

    func compress(_ draft: CompressDraft) {
        let request = PackRequest(
            format: draft.format,
            level: draft.level,
            password: draft.password,
            encryptNames: draft.encryptNames,
            volumeBytes: draft.volumeBytes
        ).sanitized()
        do {
            let run = try engine.pack(draft.sources, into: draft.folder, name: draft.name, request: request)
            tasks.start(.pack, title: "Compress \(draft.name).\(draft.format)", archive: nil, run: run) { [weak self] result in
                guard let self, self.currentFolder?.standardizedFileURL == draft.folder.standardizedFileURL else { return }
                self.reload(selecting: result.outputs.map(\.lastPathComponent))
            }
        } catch {
            show(error: "Could not start the ex engine: \(error.localizedDescription)")
        }
    }

    // MARK: Drag and drop

    /// Dropped archives open; anything else is offered for compressing.
    func handleDrop(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        if urls.allSatisfy({ FormatCatalog.isArchive(fileName: $0.lastPathComponent) }) {
            openArchive(urls[0])
        } else {
            beginCompress(urls)
        }
    }

    /// What a row offers when dragged out: the file itself, or a file extracted on demand.
    func itemProvider(for item: BrowserItem) -> NSItemProvider? {
        if let url = item.url { return NSItemProvider(contentsOf: url) }
        guard let archive = location.archiveURL, let inner = item.innerPath else { return nil }
        let provider = NSItemProvider()
        provider.suggestedName = item.name
        let type = item.isFolder ? UTType.folder : (UTType(filenameExtension: (item.name as NSString).pathExtension) ?? .data)
        let engine = engine
        let folder = cacheFolder.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let password = knownPassword(for: archive)
        provider.registerFileRepresentation(for: type, visibility: .all, openInPlace: false) { completion in
            DragExtraction.start(engine: engine, archive: archive, inner: inner, into: folder, password: password, completion: completion)
            return nil
        }
        return provider
    }
}

/// Extraction for drags, which cannot show a password prompt mid-drop.
enum DragExtraction {
    /// AppKit's completion handler is not marked Sendable, but it is safe to call from any thread.
    private struct Completion: @unchecked Sendable {
        let call: (URL?, Bool, (any Error)?) -> Void
    }

    nonisolated static func start(
        engine: Engine, archive: URL, inner: String, into folder: URL, password: String?,
        completion: @escaping (URL?, Bool, (any Error)?) -> Void
    ) {
        let box = Completion(call: completion)
        Task.detached {
            let url = await run(engine: engine, archive: archive, inner: inner, into: folder, password: password)
            box.call(url, false, url == nil ? CocoaError(.fileReadUnknown) : nil)
        }
    }

    nonisolated static func run(engine: Engine, archive: URL, inner: String, into folder: URL, password: String?) async -> URL? {
        guard let run = try? engine.extract(archive, into: folder, only: [inner]) else { return nil }
        var offered = false
        for await event in run.events {
            switch event {
            case .password:
                run.reply(password: offered ? nil : password)
                offered = true
            case .done(let result):
                return result.outputs.first
            default:
                break
            }
        }
        return nil
    }
}
