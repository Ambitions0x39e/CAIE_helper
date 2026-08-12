import 'dart:typed_data';
import 'dart:ui';

import 'package:flet/flet.dart';
import 'package:pdfrx/pdfrx.dart';

/// Headless PDF renderer service.
///
/// Handles the "render_regions" method invoked from Python: opens a PDF from
/// a filesystem path and renders each clip (full-width vertical slice, in PDF
/// points, top-origin) to a PNG at the requested dpi. Returns one PNG per clip.
///
/// The PDF arrives as a **path, not bytes**. Python and Dart are two sides of
/// one process, so the file is already reachable here; shipping its contents
/// over the Flet RPC instead used to stall the transport on a large answer
/// export (a 35MB GoodNotes scan hung with no result and no error). A path is
/// ~100 bytes no matter how big the document is.
class PdfRendererService extends FletService {
  PdfRendererService({required super.control});

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    switch (name) {
      case "render_regions":
        return await _renderRegions(args);
      default:
        throw Exception("Unknown PdfRenderer method: $name");
    }
  }

  Future<List<Uint8List>> _renderRegions(dynamic args) async {
    await pdfrxFlutterInitialize();

    final pdfPath = args["pdf_path"] as String;
    final clips = (args["clips"] as List);
    final dpi = (args["dpi"] as num).toDouble();
    final scale = dpi / 72.0;

    final doc = await PdfDocument.openFile(pdfPath);
    try {
      final out = <Uint8List>[];
      for (final c in clips) {
        final page = doc.pages[(c["page"] as num).toInt()];
        final yTopPx = ((c["y_top"] as num).toDouble() * scale).round();
        final yBottomPx = ((c["y_bottom"] as num).toDouble() * scale).round();
        final fullWidth = page.width * scale;
        final fullHeight = page.height * scale;

        final pdfImage = await page.render(
          x: 0,
          y: yTopPx,
          width: (page.width * scale).round(),
          height: (yBottomPx - yTopPx),
          fullWidth: fullWidth,
          fullHeight: fullHeight,
          backgroundColor: 0xffffffff,
        );
        if (pdfImage == null) {
          continue;
        }
        final uiImage = await pdfImage.createImage();
        final png =
            (await uiImage.toByteData(format: ImageByteFormat.png))!
                .buffer
                .asUint8List();
        pdfImage.dispose();
        uiImage.dispose();
        out.add(png);
      }
      return out;
    } finally {
      await doc.dispose();
    }
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    super.dispose();
  }
}
