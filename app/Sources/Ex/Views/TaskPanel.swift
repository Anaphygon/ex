import ExCore
import SwiftUI

struct TaskRow: View {
    @Environment(AppModel.self) private var model
    let task: TaskItem

    private var symbol: String {
        switch task.kind {
        case .extract: "arrow.down.doc.fill"
        case .pack: "archivebox.fill"
        case .open: "eye.fill"
        }
    }

    private var tint: Color {
        switch task.state {
        case .done: .green
        case .failed: .red
        case .cancelled: .secondary
        default: .exOrange
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 28, height: 28)
                .background(tint.gradient, in: Circle())
            VStack(alignment: .leading, spacing: 4) {
                Text(task.title).font(.callout.weight(.medium)).lineLimit(1).truncationMode(.middle)
                switch task.state {
                case .running:
                    if let percent = task.percent {
                        ProgressView(value: Double(percent), total: 100).tint(.exOrange)
                    } else {
                        ProgressView().progressViewStyle(.linear).tint(.exOrange)
                    }
                case .waitingPassword:
                    Text("Waiting for password…").font(.caption).foregroundStyle(.orange)
                case .done(let result):
                    Text("Done · \(result.files) files, \(Formatting.bytes(result.bytes))\(result.notes.isEmpty ? "" : " · " + result.notes.joined(separator: ", "))")
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                case .failed(let message):
                    Text(message).font(.caption).foregroundStyle(.red).lineLimit(2)
                case .cancelled:
                    Text("Cancelled").font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 4)
            if task.isFinished {
                if case .done(let result) = task.state, !result.outputs.isEmpty {
                    Button {
                        NSWorkspace.shared.activateFileViewerSelecting(result.outputs)
                    } label: {
                        Image(systemName: "magnifyingglass")
                    }
                    .buttonStyle(.borderless)
                    .help("Show in Finder")
                }
                Button {
                    model.tasks.remove(task)
                } label: {
                    Image(systemName: "xmark")
                }
                .buttonStyle(.borderless)
                .help("Dismiss")
            } else {
                Button {
                    model.tasks.cancel(task)
                } label: {
                    Image(systemName: "stop.circle.fill").font(.title3)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
                .help("Cancel")
            }
        }
    }
}

/// Floating card listing running and finished work.
struct TaskPanel: View {
    @Environment(AppModel.self) private var model
    @State private var collapsed = false

    var body: some View {
        let tasks = model.tasks.visibleTasks
        if !tasks.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Button {
                        withAnimation(.snappy) { collapsed.toggle() }
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "chevron.down")
                                .rotationEffect(.degrees(collapsed ? -90 : 0))
                            Text(model.tasks.activeCount > 0 ? "\(model.tasks.activeCount) running" : "All done")
                                .fontWeight(.semibold)
                        }
                    }
                    .buttonStyle(.plain)
                    Spacer()
                    if tasks.contains(where: \.isFinished) {
                        Button("Clear") { withAnimation { model.tasks.clearFinished() } }
                            .buttonStyle(.borderless)
                            .font(.callout)
                    }
                }
                if !collapsed {
                    ForEach(tasks) { task in
                        TaskRow(task: task)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
            }
            .padding(14)
            .frame(maxWidth: 480)
            .exGlass(cornerRadius: 20)
            .animation(.snappy, value: tasks.map(\.id))
        }
    }
}
