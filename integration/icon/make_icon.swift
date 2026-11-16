// Draws the Ex app icon: an open zipper. Run with: swift make_icon.swift out.png
import AppKit

let canvas: CGFloat = 1024
let tile = NSRect(x: 100, y: 100, width: 824, height: 824)
let cornerRadius: CGFloat = 186
let centerX: CGFloat = 512
let sliderY: CGFloat = 456
let openingHalfWidth: CGFloat = 268
let toothLength: CGFloat = 46
let toothThickness: CGFloat = 19
let toothSpacing: CGFloat = 52

func rgb(_ hex: UInt32, _ alpha: CGFloat = 1) -> NSColor {
    NSColor(
        srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
        green: CGFloat((hex >> 8) & 0xFF) / 255,
        blue: CGFloat(hex & 0xFF) / 255,
        alpha: alpha
    )
}

let ink = rgb(0x24123F)
let cream = rgb(0xFFF3D1)

func cubic(_ a: NSPoint, _ b: NSPoint, _ c: NSPoint, _ d: NSPoint, _ t: CGFloat) -> NSPoint {
    let u = 1 - t
    let x = u * u * u * a.x + 3 * u * u * t * b.x + 3 * u * t * t * c.x + t * t * t * d.x
    let y = u * u * u * a.y + 3 * u * u * t * b.y + 3 * u * t * t * c.y + t * t * t * d.y
    return NSPoint(x: x, y: y)
}

func drawTooth(at point: NSPoint, angle: CGFloat) {
    let transform = NSAffineTransform()
    transform.translateX(by: point.x, yBy: point.y)
    transform.rotate(byRadians: angle)
    let rect = NSRect(x: 0, y: -toothThickness / 2, width: toothLength, height: toothThickness)
    let tooth = NSBezierPath(roundedRect: rect, xRadius: 6, yRadius: 6)
    tooth.transform(using: transform as AffineTransform)
    tooth.fill()
}

/// Teeth along one curve, spaced by arc length rather than by parameter.
func drawTeeth(from a: NSPoint, _ b: NSPoint, _ c: NSPoint, to d: NSPoint, side: CGFloat) {
    let steps = 800
    var travelled: CGFloat = 0
    var previous = a
    var nextTooth = toothSpacing * 0.6
    for index in 1...steps {
        let point = cubic(a, b, c, d, CGFloat(index) / CGFloat(steps))
        let step = hypot(point.x - previous.x, point.y - previous.y)
        travelled += step
        if travelled >= nextTooth {
            let tangent = atan2(point.y - previous.y, point.x - previous.x)
            drawTooth(at: point, angle: tangent + side * .pi / 2)
            nextTooth += toothSpacing
        }
        previous = point
    }
}

let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: Int(canvas), pixelsHigh: Int(canvas),
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)

let squircle = NSBezierPath(roundedRect: tile, xRadius: cornerRadius, yRadius: cornerRadius)

// The tile and its soft shadow.
NSGraphicsContext.saveGraphicsState()
let dropShadow = NSShadow()
dropShadow.shadowColor = NSColor.black.withAlphaComponent(0.32)
dropShadow.shadowBlurRadius = 30
dropShadow.shadowOffset = NSSize(width: 0, height: -14)
dropShadow.set()
rgb(0xFF9A0A).setFill()
squircle.fill()
NSGraphicsContext.restoreGraphicsState()

NSGraphicsContext.saveGraphicsState()
squircle.addClip()
NSGradient(starting: rgb(0xFFC933), ending: rgb(0xFF6B00))!.draw(in: tile, angle: -90)

// The opened mouth of the zipper.
let top = tile.maxY + 20
let leftTop = NSPoint(x: centerX - openingHalfWidth, y: top)
let rightTop = NSPoint(x: centerX + openingHalfWidth, y: top)
let bottom = NSPoint(x: centerX, y: sliderY)
let leftControlA = NSPoint(x: centerX - openingHalfWidth, y: top - 250)
let leftControlB = NSPoint(x: centerX - 26, y: sliderY + 190)
let rightControlA = NSPoint(x: centerX + openingHalfWidth, y: top - 250)
let rightControlB = NSPoint(x: centerX + 26, y: sliderY + 190)

let mouth = NSBezierPath()
mouth.move(to: leftTop)
mouth.curve(to: bottom, controlPoint1: leftControlA, controlPoint2: leftControlB)
mouth.curve(to: rightTop, controlPoint1: rightControlB, controlPoint2: rightControlA)
mouth.close()
ink.setFill()
mouth.fill()

// Teeth on both opened edges, pointing into the mouth.
cream.setFill()
drawTeeth(from: leftTop, leftControlA, leftControlB, to: bottom, side: -1)
drawTeeth(from: rightTop, rightControlA, rightControlB, to: bottom, side: 1)

// The closed run below the slider: alternating teeth meeting in the middle.
var y = sliderY - 40
var fromLeft = true
while y > tile.minY - 20 {
    let start = NSPoint(x: fromLeft ? centerX - 34 : centerX + 34, y: y)
    drawTooth(at: start, angle: fromLeft ? 0 : .pi)
    fromLeft.toggle()
    y -= toothSpacing / 2
}
NSGraphicsContext.restoreGraphicsState()

// The slider and its pull tab sit on top of everything.
NSGraphicsContext.saveGraphicsState()
let sliderShadow = NSShadow()
sliderShadow.shadowColor = ink.withAlphaComponent(0.45)
sliderShadow.shadowBlurRadius = 22
sliderShadow.shadowOffset = NSSize(width: 0, height: -10)
sliderShadow.set()
let tab = NSBezierPath(
    roundedRect: NSRect(x: centerX - 54, y: sliderY - 270, width: 108, height: 260),
    xRadius: 54, yRadius: 54
)
ink.setFill()
tab.fill()
let slider = NSBezierPath(
    roundedRect: NSRect(x: centerX - 92, y: sliderY - 62, width: 184, height: 124),
    xRadius: 40, yRadius: 40
)
ink.setFill()
slider.fill()
NSGraphicsContext.restoreGraphicsState()

let tabHole = NSBezierPath(
    roundedRect: NSRect(x: centerX - 22, y: sliderY - 240, width: 44, height: 112),
    xRadius: 22, yRadius: 22
)
rgb(0xFF8A14).setFill()
tabHole.fill()
let sliderGlint = NSBezierPath(
    roundedRect: NSRect(x: centerX - 58, y: sliderY + 12, width: 116, height: 18),
    xRadius: 9, yRadius: 9
)
cream.withAlphaComponent(0.85).setFill()
sliderGlint.fill()

NSGraphicsContext.restoreGraphicsState()
try! bitmap.representation(using: .png, properties: [:])!
    .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
