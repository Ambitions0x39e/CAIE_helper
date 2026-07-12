import 'package:flet/flet.dart';

import 'pdf_renderer_service.dart';

class Extension extends FletExtension {
  @override
  FletService? createService(Control control) {
    switch (control.type) {
      case "PdfRenderer":
        return PdfRendererService(control: control);
      default:
        return null;
    }
  }
}
