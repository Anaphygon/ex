import ExCore
import SwiftUI

/// Clickable breadcrumb of where the browser is.
struct PathBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 2) {
                let segments = model.pathSegments
                ForEach(Array(segments.enumerated()), id: \.offset) { index, segment in
                    if index > 0 {
                        Image(systemName: "chevron.compact.right")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                    let isLast = index == segments.count - 1
                    Button {
                        model.go(to: segment.target)
                    } label: {
                        HStack(spacing: 4) {
                            if case .archive(let url, let inner) = segment.target, inner.isEmpty,
                               let info = FormatCatalog.info(forFileName: url.lastPathComponent) {
                                FormatBadge(info: info)
                            }
                            Text(segment.title)
                                .fontWeight(isLast ? .semibold : .regular)
                                .foregroundStyle(isLast ? .primary : .secondary)
                        }
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(isLast)
                }
            }
        }
    }
}

/// The summary card shown while inside an archive, with its main actions.
struct ArchiveHero: View {
    @Environment(AppModel.self) private var model
    let session: ArchiveSession

    private var info: FormatInfo {
        FormatCatalog.info(forFileName: session.url.lastPathComponent) ?? FormatInfo(label: session.label.uppercased(), family: .other)
    }

    var body: some View {
        HStack(spacing: 14) {
            FormatTile(info: info)
            VStack(alignment: .leading, spacing: 4) {
                Text(session.url.lastPathComponent)
                    .font(.title3.weight(.semibold))
                    .lineLimit(1)
                    .truncationMode(.middle)
                HStack(spacing: 10) {
                    Label("\(session.tree.fileCount) files", systemImage: "doc.on.doc")
                    Label("\(Formatting.bytes(session.tree.totalSize)) unpacked", systemImage: "shippingbox")
                    if let ratio = Formatting.ratio(packed: session.diskSize, size: session.tree.totalSize), ratio < 1 {
                        Label("saves \(Int(((1 - ratio) * 100).rounded()))%", systemImage: "arrow.down.right.and.arrow.up.left")
                    }
                    if session.tree.hasEncryptedEntries {
                        Label("Password protected", systemImage: "lock.fill").foregroundStyle(.orange)
                    }
                }
                .font(.callout)
                .foregroundStyle(.secondary)
                .labelStyle(.titleAndIcon)
            }
            Spacer(minLength: 12)
            Button {
                model.chooseDestination { model.extractAll(into: $0) }
            } label: {
                Label("Extract To…", systemImage: "folder.badge.plus")
            }
            .buttonStyle(.glass)
            .controlSize(.large)
            Button {
                model.extractAll()
            } label: {
                Label("Extract All", systemImage: "arrow.down.to.line")
                    .fontWeight(.semibold)
            }
            .buttonStyle(.glassProminent)
            .tint(.exOrange)
            .controlSize(.large)
            .keyboardShortcut("e", modifiers: [.command, .shift])
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
    }
}

struct LocationHeader: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let session = model.session {
                ArchiveHero(session: session)
                Divider().padding(.horizontal, 18)
            }
            HStack {
                PathBar()
                Spacer(minLength: 8)
                if model.location.archiveURL == nil {
                    Text("\(model.items.count) items")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
        .exBar()
    }
}
