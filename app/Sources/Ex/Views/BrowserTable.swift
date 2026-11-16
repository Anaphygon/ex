import ExCore
import SwiftUI

struct NameCell: View {
    let item: BrowserItem

    var body: some View {
        HStack(spacing: 7) {
            Image(nsImage: Icons.image(for: item))
                .resizable()
                .frame(width: 18, height: 18)
            Text(item.name)
                .lineLimit(1)
                .truncationMode(.middle)
            if item.encrypted {
                Image(systemName: "lock.fill")
                    .font(.caption2)
                    .foregroundStyle(.orange)
                    .help("Encrypted")
            }
            if item.kind == .archive, let format = item.format {
                FormatBadge(info: format)
            }
        }
    }
}

struct SizeText: View {
    let bytes: Int64?
    var fileCount: Int?

    var body: some View {
        Group {
            if let bytes, bytes >= 0 {
                Text(Formatting.bytes(bytes))
            } else if let fileCount {
                Text("\(fileCount) files")
            } else {
                Text("—").foregroundStyle(.tertiary)
            }
        }
        .monospacedDigit()
        .foregroundStyle(.secondary)
    }
}

struct DateText: View {
    let date: Date?

    var body: some View {
        if let date {
            Text(date, format: .dateTime.day().month(.abbreviated).year().hour().minute())
                .foregroundStyle(.secondary)
        } else {
            Text("—").foregroundStyle(.tertiary)
        }
    }
}

/// The file list. Archives get an extra column for the compressed size.
struct BrowserTable: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        Group {
            // Solid 7z and many rar archives do not report packed sizes per file;
            // a column of dashes says nothing, so it only appears when it has data.
            if model.location.archiveURL != nil, model.items.contains(where: { $0.packed != nil }) {
                Table(of: BrowserItem.self, selection: $model.selection, sortOrder: $model.sortOrder) {
                    TableColumn("Name", value: \.name, comparator: .localizedStandard) { NameCell(item: $0) }
                        .width(min: 220, ideal: 380)
                    TableColumn("Size", value: \.sizeKey) { SizeText(bytes: $0.size) }
                        .width(min: 70, ideal: 90)
                    TableColumn("Packed", value: \.packedKey) { item in
                        SizeText(bytes: item.packed)
                    }
                    .width(min: 80, ideal: 100)
                    TableColumn("Modified", value: \.modifiedKey) { DateText(date: $0.modified) }
                        .width(min: 120, ideal: 160)
                    TableColumn("Kind", value: \.kindLabel) { Text($0.kindLabel).foregroundStyle(.secondary) }
                        .width(min: 80, ideal: 120)
                } rows: {
                    rows
                }
            } else {
                Table(of: BrowserItem.self, selection: $model.selection, sortOrder: $model.sortOrder) {
                    TableColumn("Name", value: \.name, comparator: .localizedStandard) { NameCell(item: $0) }
                        .width(min: 220, ideal: 420)
                    TableColumn("Size", value: \.sizeKey) { SizeText(bytes: $0.size) }
                        .width(min: 70, ideal: 90)
                    TableColumn("Modified", value: \.modifiedKey) { DateText(date: $0.modified) }
                        .width(min: 120, ideal: 160)
                    TableColumn("Kind", value: \.kindLabel) { Text($0.kindLabel).foregroundStyle(.secondary) }
                        .width(min: 80, ideal: 140)
                } rows: {
                    rows
                }
            }
        }
        .contextMenu(forSelectionType: BrowserItem.ID.self) { ids in
            ItemMenu(ids: ids)
        } primaryAction: { ids in
            model.open(ids)
        }
        .onKeyPress(.space) {
            model.previewSelection()
            return .handled
        }
    }

    @TableRowBuilder<BrowserItem>
    private var rows: some TableRowContent<BrowserItem> {
        ForEach(model.displayedItems) { item in
            TableRow(item)
                .itemProvider { model.itemProvider(for: item) }
        }
    }
}

/// Right-click menu for the selected rows.
struct ItemMenu: View {
    @Environment(AppModel.self) private var model
    let ids: Set<BrowserItem.ID>

    var body: some View {
        let inArchive = model.location.archiveURL != nil
        // Act on the rows the menu was opened for, which need not be the selection.
        let picked = model.items(for: ids)
        if !ids.isEmpty {
            Button("Open") { model.open(ids) }
            if !inArchive {
                Button("Show in Finder") { model.revealInFinder(picked) }
            }
            Divider()
        }
        if model.canExtract(picked) {
            Button(inArchive && ids.isEmpty ? "Extract All Here" : "Extract Here") { model.extract(picked) }
            Button("Extract To…") { model.chooseDestination { model.extract(picked, into: $0) } }
        }
        if model.canCompress(picked) {
            Divider()
            Button("Compress…") { model.beginCompress(picked.compactMap(\.url)) }
        }
    }
}
