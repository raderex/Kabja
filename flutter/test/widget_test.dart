// Kabja smoke test — renders without throwing.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ktm_bus_tracker/main.dart';

void main() {
  testWidgets('KabjaApp smoke test — renders without throwing',
      (WidgetTester tester) async {
    await tester.pumpWidget(
      const ProviderScope(child: KabjaApp()),
    );
    // App should render (splash screen) without throwing
    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
