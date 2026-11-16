import ExCore
import SwiftUI

struct StatusBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 12) {
            let selected = model.selectedItems
            if selected.isEmpty {
                Text("\(model.displayedItems.count) items")
            } else {
                let bytes = selected.compactMap(\.size).reduce(0, +)
                Text("\(selected.count) selected\(bytes > 0 ? " · " + Formatting.bytes(bytes) : "")")
            }
            Spacer()
            if model.location.archiveURL == nil, let free = FileSystem.freeSpace(at: model.workingFolder) {
                Label("\(Formatting.bytes(free)) available", systemImage: "internaldrive")
            }
        }
        .font(.callout)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
        .exBar()
    }
}

/// Shown over the window while files are dragged onto it.
struct DropOverlay: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(Color.exOrange.opacity(0.08))
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(Color.exOrange, style: StrokeStyle(lineWidth: 2.5, dash: [10, 7]))
            VStack(spacing: 10) {
                Image(systemName: "arrow.down.circle.fill")
                    .font(.system(size: 44))
                    .foregroundStyle(Color.exOrange)
                Text("Drop here").font(.title2.weight(.semibold))
                Text("Archives open · anything else gets compressed").foregroundStyle(.secondary)
            }
            .padding(28)
            .exGlass(cornerRadius: 22)
        }
        .padding(14)
        .allowsHitTesting(false)
    }
}
