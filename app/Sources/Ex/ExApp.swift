import AppKit
import ExCore
import SwiftUI

/// English text, but the user's own region for date and number conventions.
private let englishLocale = Locale(identifier: "en_\(Locale.current.region?.identifier ?? "US")")

@main
struct ExApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel.shared

    var body: some Scene {
        Window("Ex", id: "main") {
            RootView()
                .environment(model)
                .environment(\.locale, englishLocale)
                .tint(.exOrange)
        }
        .defaultSize(width: 1120, height: 720)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Open Archive…") { openPanel() }
                    .keyboardShortcut("o")
            }
            CommandMenu("Archive") {
                Button("Extract Here") { model.extract() }
                    .keyboardShortcut("e")
                    .disabled(!model.canExtract)
                Button("Extract To…") { model.chooseDestination { model.extract(into: $0) } }
                    .keyboardShortcut("e", modifiers: [.command, .option])
                    .disabled(!model.canExtract)
                Divider()
                Button("Compress…") { model.beginCompress() }
                    .keyboardShortcut("k")
                    .disabled(!model.canCompress)
                Divider()
                Button("Reload") { model.reload() }
                    .keyboardShortcut("r")
            }
        }
    }

    @MainActor private func openPanel() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.directoryURL = model.workingFolder
        if panel.runModal() == .OK, let url = panel.url { model.openArchive(url) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func application(_ application: NSApplication, open urls: [URL]) {
        MainActor.assumeIsolated { AppModel.shared.openFromFinder(urls) }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        #if DEBUG
        MainActor.assumeIsolated { Snapshot.runIfRequested() }
        #endif
    }
}
