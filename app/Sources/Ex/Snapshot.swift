#if DEBUG
import AppKit
import ExCore
import SwiftUI

/// Debug-only: `EX_SNAPSHOT=out.png [EX_OPEN=path] [EX_SELECT=name] Ex` renders the
/// window to a PNG and quits, so layouts can be checked without screen recording rights.
@MainActor enum Snapshot {
    static func runIfRequested() {
        let environment = ProcessInfo.processInfo.environment
        guard let output = environment["EX_SNAPSHOT"] else { return }
        let model = AppModel.shared
        if let path = environment["EX_OPEN"] {
            model.openFromFinder([URL(fileURLWithPath: path)])
        }
        if environment["EX_COMPRESS"] != nil {
            model.beginCompress(model.items.prefix(2).compactMap(\.url))
        }
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(Double(environment["EX_DELAY"] ?? "3") ?? 3))
            if let inner = environment["EX_INNER"], let archive = model.location.archiveURL {
                model.go(to: .archive(archive, inner))
                try? await Task.sleep(for: .seconds(1.5))
            }
            if environment["EX_EXTRACT_ALL"] != nil {
                model.extractAll()
                try? await Task.sleep(for: .seconds(2))
            }
            if let name = environment["EX_SELECT"] {
                model.selection = Set(model.items.filter { $0.name == name }.map(\.id))
                try? await Task.sleep(for: .seconds(1.5))
            }
            let windows = NSApp.windows.filter { $0.isVisible && $0.contentView != nil }
            // "screen" mode: report the window so `screencapture -l` can photograph
            // the real thing, glass included, then stay up long enough for it.
            if output == "screen" {
                print("window=\(windows.first?.windowNumber ?? 0)")
                fflush(stdout)
                try? await Task.sleep(for: .seconds(3))
                exit(0)
            }
            for (index, window) in windows.enumerated() {
                let view = window.contentView!.superview ?? window.contentView!
                guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { continue }
                view.cacheDisplay(in: view.bounds, to: bitmap)
                let path = index == 0 ? output : output.replacingOccurrences(of: ".png", with: "-\(index).png")
                try? bitmap.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
                print("snapshot window=\(window.windowNumber) \(path)")
            }
            // terminate() is refused while a sheet is up; a snapshot run just ends.
            exit(0)
        }
    }
}
#endif
