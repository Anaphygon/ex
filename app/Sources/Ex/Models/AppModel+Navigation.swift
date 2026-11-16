import AppKit
import ExCore
import Foundation

extension AppModel {
    var session: ArchiveSession? {
        location.archiveURL.flatMap { sessions[$0] }
    }

    var currentFolder: URL? {
        if case .folder(let url) = location { return url }
        return nil
    }

    /// The folder on disk that actions like "extract here" write into.
    var workingFolder: URL {
        switch location {
        case .folder(let url): url
        case .archive(let url, _): url.deletingLastPathComponent()
        }
    }

    var displayedItems: [BrowserItem] {
        let query = search.trimmingCharacters(in: .whitespaces)
        let matching = query.isEmpty ? items : items.filter { $0.name.localizedCaseInsensitiveContains(query) }
        return matching.sorted { lhs, rhs in
            if lhs.isFolder != rhs.isFolder { return lhs.isFolder }
            for comparator in sortOrder {
                let order = comparator.compare(lhs, rhs)
                if order != .orderedSame { return order == .orderedAscending }
            }
            return false
        }
    }

    var selectedItems: [BrowserItem] {
        items.filter { selection.contains($0.id) }
    }

    var title: String {
        switch location {
        case .folder(let url): FileManager.default.displayName(atPath: url.path)
        case .archive(let url, let inner): inner.isEmpty ? url.lastPathComponent : (inner as NSString).lastPathComponent
        }
    }

    // MARK: Moving around

    func go(to target: Location) {
        guard target != location else { return }
        backStack.append(location)
        forwardStack.removeAll()
        location = target
        reload()
    }

    func goBack() {
        guard let previous = backStack.popLast() else { return }
        forwardStack.append(location)
        location = previous
        reload()
    }

    func goForward() {
        guard let next = forwardStack.popLast() else { return }
        backStack.append(location)
        location = next
        reload()
    }

    var canGoUp: Bool {
        if case .folder(let url) = location { return url.path != "/" }
        return true
    }

    func goUp() {
        switch location {
        case .folder(let url):
            go(to: .folder(url.deletingLastPathComponent()))
        case .archive(let url, let inner):
            if inner.isEmpty {
                go(to: .folder(url.deletingLastPathComponent()))
            } else {
                let parent = (inner as NSString).deletingLastPathComponent
                go(to: .archive(url, parent))
            }
        }
    }

    /// Re-reads the current location. Archive listings come from memory.
    func reload(selecting names: [String] = []) {
        switch location {
        case .folder(let url):
            do {
                items = try FileSystem.items(in: url)
                rememberFolder(url)
            } catch {
                items = []
                show(error: error.localizedDescription, title: "Could not open the folder")
            }
        case .archive(let url, let inner):
            let node = sessions[url]?.tree.node(at: inner)
            items = node?.children.map(BrowserItem.inArchive) ?? []
        }
        selection = Set(items.filter { names.contains($0.name) }.map(\.id))
    }

    /// Lists `url` and, once that works, shows its contents.
    func openArchive(_ url: URL) {
        if sessions[url] != nil {
            rememberArchive(url)
            go(to: .archive(url, ""))
            return
        }
        let run: EngineRun
        do {
            run = try engine.list(url)
        } catch {
            show(error: "Could not start the ex engine: \(error.localizedDescription)")
            return
        }
        busyMessage = "Reading \(url.lastPathComponent)…"
        Task { @MainActor in
            for await event in run.events {
                switch event {
                case .password(_, let retry):
                    answerPassword(for: url, retry: retry, run: run)
                case .listing(let label, let entries):
                    let diskSize = Int64((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
                    sessions[url] = ArchiveSession(url: url, label: label, tree: ArchiveTree(entries: entries), diskSize: diskSize)
                    rememberArchive(url)
                    go(to: .archive(url, ""))
                case .error(let message):
                    show(error: message, title: "Could not open \(url.lastPathComponent)")
                default:
                    break
                }
            }
            withdrawPrompts(for: run)
            busyMessage = nil
        }
    }

    /// Opens what Finder hands over: archives as archives, folders as folders.
    func openFromFinder(_ urls: [URL]) {
        NSApp.activate()
        guard let first = urls.first else { return }
        var isDirectory: ObjCBool = false
        FileManager.default.fileExists(atPath: first.path, isDirectory: &isDirectory)
        if isDirectory.boolValue {
            go(to: .folder(first))
        } else {
            openArchive(first)
        }
    }

    /// Breadcrumb segments, root first.
    var pathSegments: [(title: String, target: Location)] {
        switch location {
        case .folder(let url):
            return folderSegments(url)
        case .archive(let url, let inner):
            var segments = folderSegments(url.deletingLastPathComponent()).suffix(2).map { $0 }
            segments.append((url.lastPathComponent, .archive(url, "")))
            var path = ""
            for part in inner.split(separator: "/") {
                path = path.isEmpty ? String(part) : "\(path)/\(part)"
                segments.append((String(part), .archive(url, path)))
            }
            return segments
        }
    }

    private func folderSegments(_ url: URL) -> [(title: String, target: Location)] {
        let home = FileManager.default.homeDirectoryForCurrentUser.standardizedFileURL.path
        var segments: [(String, Location)] = []
        var current = url.standardizedFileURL
        while true {
            let name = current.path == home ? "Home" : FileManager.default.displayName(atPath: current.path)
            segments.insert((name, .folder(current)), at: 0)
            if current.path == home || current.path == "/" { break }
            current = current.deletingLastPathComponent()
        }
        return segments
    }
}
