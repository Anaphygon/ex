import ExCore
import QuickLook
import SwiftUI

struct SidebarView: View {
    @Environment(AppModel.self) private var model

    private struct Place: Identifiable {
        let title: String
        let symbol: String
        let url: URL
        var id: URL { url }
    }

    private var places: [Place] {
        let manager = FileManager.default
        func folder(_ directory: FileManager.SearchPathDirectory) -> URL {
            manager.urls(for: directory, in: .userDomainMask)[0]
        }
        return [
            Place(title: "Downloads", symbol: "arrow.down.circle", url: folder(.downloadsDirectory)),
            Place(title: "Desktop", symbol: "menubar.dock.rectangle", url: folder(.desktopDirectory)),
            Place(title: "Documents", symbol: "doc", url: folder(.documentDirectory)),
            Place(title: "Home", symbol: "house", url: manager.homeDirectoryForCurrentUser),
        ]
    }

    var body: some View {
        let selection = Binding<URL?>(
            get: {
                switch model.location {
                case .folder(let url): url.standardizedFileURL
                case .archive(let url, _): url
                }
            },
            set: { picked in
                guard let picked else { return }
                if model.recentArchives.contains(picked) {
                    model.openArchive(picked)
                } else {
                    model.go(to: .folder(picked))
                }
            }
        )
        List(selection: selection) {
            Section("Places") {
                ForEach(places) { place in
                    Label(place.title, systemImage: place.symbol).tag(place.url.standardizedFileURL)
                }
            }
            if !model.recentArchives.isEmpty {
                Section("Recent Archives") {
                    ForEach(model.recentArchives, id: \.self) { url in
                        HStack(spacing: 8) {
                            if let info = FormatCatalog.info(forFileName: url.lastPathComponent) {
                                FormatTile(info: info, size: 18)
                            }
                            Text(url.lastPathComponent).lineLimit(1).truncationMode(.middle)
                        }
                        .tag(url)
                        .help(url.path)
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .scrollContentBackground(rendersFlat ? .hidden : .automatic)
        .background(rendersFlat ? Color(nsColor: .underPageBackgroundColor) : .clear)
    }
}

struct BrowserView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 0) {
            LocationHeader()
            ZStack {
                BrowserTable()
                if model.displayedItems.isEmpty {
                    if model.search.isEmpty {
                        ContentUnavailableView(
                            model.location.archiveURL == nil ? "This folder is empty" : "Nothing inside",
                            systemImage: model.location.archiveURL == nil ? "folder" : "archivebox",
                            description: Text("Drop an archive here to open it, or any other files to compress them.")
                        )
                    } else {
                        ContentUnavailableView.search(text: model.search)
                    }
                }
                if let message = model.busyMessage {
                    VStack(spacing: 12) {
                        ProgressView().controlSize(.large)
                        Text(message).font(.callout.weight(.medium))
                    }
                    .padding(26)
                    .exGlass(cornerRadius: 20)
                }
            }
            StatusBar()
        }
        .overlay(alignment: .bottomTrailing) {
            TaskPanel()
                .padding(.trailing, 16)
                .padding(.bottom, 40)
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var dropTargeted = false

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 180, ideal: 210, max: 280)
        } detail: {
            BrowserView()
        }
        .toolbar { BrowserToolbar() }
        .navigationTitle(model.title)
        .searchable(text: $model.search, placement: .toolbar, prompt: "Search")
        .sheet(item: $model.passwordPrompt) { PasswordSheet(prompt: $0).interactiveDismissDisabled() }
        .sheet(item: $model.compressDraft) { CompressSheet(draft: $0) }
        .alert(item: $model.alert) { alert in
            Alert(title: Text(alert.title), message: Text(alert.message))
        }
        .quickLookPreview($model.previewURL)
        .dropDestination(for: URL.self) { urls, _ in
            model.handleDrop(urls)
            return true
        } isTargeted: { dropTargeted = $0 }
        .overlay {
            if dropTargeted { DropOverlay().transition(.opacity) }
        }
        .animation(.easeOut(duration: 0.15), value: dropTargeted)
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            if model.currentFolder != nil { model.reload(selecting: model.selectedItems.map(\.name)) }
        }
        .frame(minWidth: 860, minHeight: 540)
    }
}

struct BrowserToolbar: ToolbarContent {
    @Environment(AppModel.self) private var model

    var body: some ToolbarContent {
        ToolbarItemGroup(placement: .navigation) {
            Button { model.goBack() } label: { Label("Back", systemImage: "chevron.left") }
                .disabled(model.backStack.isEmpty)
                .keyboardShortcut("[", modifiers: .command)
            Button { model.goForward() } label: { Label("Forward", systemImage: "chevron.right") }
                .disabled(model.forwardStack.isEmpty)
                .keyboardShortcut("]", modifiers: .command)
            Button { model.goUp() } label: { Label("Enclosing Folder", systemImage: "arrow.up") }
                .disabled(!model.canGoUp)
                .keyboardShortcut(.upArrow, modifiers: .command)
        }
        ToolbarItemGroup(placement: .primaryAction) {
            Menu {
                Button("Extract Here") { model.extract() }
                Button("Extract To…") { model.chooseDestination { model.extract(into: $0) } }
            } label: {
                Label("Extract", systemImage: "arrow.down.doc")
            } primaryAction: {
                model.extract()
            }
            .disabled(!model.canExtract)
            .help("Extract the archive or the selected items")
            Button { model.beginCompress() } label: {
                Label("Compress", systemImage: "archivebox")
            }
            .disabled(!model.canCompress)
            .help("Compress the selected items into an archive")
            Button { model.revealInFinder() } label: {
                Label("Finder", systemImage: "macwindow")
            }
            .help("Show in Finder")
        }
    }
}
