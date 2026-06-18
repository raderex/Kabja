class AppConfig {
  // Emulator: 10.0.2.2
  // Physical device on same WiFi: your machine's local IP (e.g. 192.168.1.100)
  // Override at build time:
  //   flutter run --dart-define=API_BASE_URL=http://192.168.1.100:8000
  //               --dart-define=WS_BASE_URL=ws://192.168.1.100:8000
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL', defaultValue: 'http://10.0.2.2:8000');
  static const wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL', defaultValue: 'ws://10.0.2.2:8000');
}
