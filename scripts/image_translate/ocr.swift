import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
if args.count < 2 { exit(1) }
let path = args[1]
guard let img = NSImage(contentsOfFile: path),
      let cgImg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("Failed to load image\n", stderr)
    exit(1)
}
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false
let handler = VNImageRequestHandler(cgImage: cgImg, options: [:])
try handler.perform([req])
var results: [[String: Any]] = []
for obs in req.results ?? [] {
    guard let cand = obs.topCandidates(1).first else { continue }
    let bb = obs.boundingBox
    results.append([
        "text": cand.string,
        "x": bb.origin.x,
        "y": bb.origin.y,
        "w": bb.size.width,
        "h": bb.size.height
    ])
}
let data = try JSONSerialization.data(withJSONObject: results, options: [])
print(String(data: data, encoding: .utf8)!)
