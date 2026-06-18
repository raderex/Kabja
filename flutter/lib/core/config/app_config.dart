class AppConfig {
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL', defaultValue: 'http://10.0.2.2:8000');
  static const wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL', defaultValue: 'ws://10.0.2.2:8000');
}
