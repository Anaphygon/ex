import AppKit
import ExCore
import SwiftUI
import UniformTypeIdentifiers

extension Color {
    /// The orange of the Ex zipper icon.
    static let exOrange = Color(red: 1.0, green: 0.54, blue: 0.08)
    static let exInk = Color(red: 0.14, green: 0.07, blue: 0.25)
}

extension FormatFamily {
    /// Each family keeps one hue everywhere, so a RAR is recognisable before it is read.
    var colors: (top: Color, bottom: Color) {
        switch self {
        case .zip: (Color(red: 1.00, green: 0.74, blue: 0.29), Color(red: 0.93, green: 0.52, blue: 0.10))
        case .sevenZip: (Color(red: 0.25, green: 0.80, blue: 0.58), Color(red: 0.06, green: 0.55, blue: 0.40))
        case .rar: (Color(red: 0.69, green: 0.50, blue: 0.98), Color(red: 0.44, green: 0.24, blue: 0.80))
        case .tar: (Color(red: 0.42, green: 0.66, blue: 1.00), Color(red: 0.16, green: 0.40, blue: 0.88))
        case .disk: (Color(red: 0.62, green: 0.67, blue: 0.75), Color(red: 0.36, green: 0.41, blue: 0.50))
        case .other: (Color(red: 0.96, green: 0.56, blue: 0.42), Color(red: 0.78, green: 0.32, blue: 0.22))
        }
    }

    var gradient: LinearGradient {
        LinearGradient(colors: [colors.top, colors.bottom], startPoint: .top, endPoint: .bottom)
    }
}

/// The small coloured label next to archive names, e.g. "RAR".
struct FormatBadge: View {
    let info: FormatInfo

    var body: some View {
        Text(info.label)
            .font(.system(size: 9, weight: .heavy, design: .rounded))
            .foregroundStyle(.white)
            .padding(.horizontal, 5)
            .padding(.vertical, 1.5)
            .background(info.family.gradient, in: RoundedRectangle(cornerRadius: 4, style: .continuous))
            .accessibilityLabel("\(info.label) archive")
    }
}

/// The big tile at the top of an open archive.
struct FormatTile: View {
    let info: FormatInfo
    var size: CGFloat = 56

    var body: some View {
        ZStack(alignment: .bottom) {
            RoundedRectangle(cornerRadius: size * 0.26, style: .continuous)
                .fill(info.family.gradient)
            // A row of zipper teeth along the bottom edge.
            HStack(spacing: size * 0.06) {
                ForEach(0..<5, id: \.self) { _ in
                    Capsule().fill(.white.opacity(0.35)).frame(width: size * 0.08, height: size * 0.14)
                }
            }
            .padding(.bottom, size * 0.1)
            Text(info.label)
                .font(.system(size: size * (info.label.count > 4 ? 0.2 : 0.27), weight: .black, design: .rounded))
                .foregroundStyle(.white)
                .shadow(color: .black.opacity(0.25), radius: 1, y: 1)
                .frame(maxHeight: .infinity)
        }
        .frame(width: size, height: size)
        .shadow(color: info.family.colors.bottom.opacity(0.35), radius: 8, y: 4)
    }
}

/// Finder's own icon for a file, cached per type because tables redraw often.
@MainActor enum Icons {
    private static var byType: [String: NSImage] = [:]

    static func image(for item: BrowserItem) -> NSImage {
        if let url = item.url {
            return NSWorkspace.shared.icon(forFile: url.path)
        }
        let key = item.isFolder ? "public.folder" : (item.name as NSString).pathExtension.lowercased()
        if let cached = byType[key] { return cached }
        let type = item.isFolder ? UTType.folder : (UTType(filenameExtension: key) ?? .data)
        let icon = NSWorkspace.shared.icon(for: type)
        byType[key] = icon
        return icon
    }
}

/// Debug snapshots render with `cacheDisplay`, which cannot draw window-server
/// materials. With `EX_FLAT` set they are swapped for solid fills instead.
let rendersFlat: Bool = {
    #if DEBUG
    ProcessInfo.processInfo.environment["EX_FLAT"] != nil
    #else
    false
    #endif
}()

extension View {
    @ViewBuilder
    func exGlass(cornerRadius: CGFloat) -> some View {
        if rendersFlat {
            background(Color(nsColor: .controlBackgroundColor), in: .rect(cornerRadius: cornerRadius))
                .overlay(RoundedRectangle(cornerRadius: cornerRadius).strokeBorder(.separator))
                .shadow(color: .black.opacity(0.25), radius: 12, y: 6)
        } else {
            glassEffect(.regular, in: .rect(cornerRadius: cornerRadius))
        }
    }

    @ViewBuilder
    func exBar() -> some View {
        if rendersFlat {
            background(Color(nsColor: .underPageBackgroundColor))
        } else {
            background(.bar)
        }
    }
}
