import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class ApiClient {
  final String Function() _getToken;
  final String _base = AppConfig.apiBaseUrl;

  ApiClient({required String Function() getToken}) : _getToken = getToken;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${_getToken()}',
      };

  Future<Map<String, dynamic>> get(String path, {bool auth = true}) async {
    final res = await http.get(
      Uri.parse('$_base$path'),
      headers: auth ? _headers : {'Content-Type': 'application/json'},
    );
    if (res.statusCode >= 400) throw ApiException(res.statusCode, res.body);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> post(String path, Map<String, dynamic> body,
      {bool auth = true}) async {
    final res = await http.post(
      Uri.parse('$_base$path'),
      headers: auth ? _headers : {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    if (res.statusCode >= 400) throw ApiException(res.statusCode, res.body);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  Future<void> delete(String path) async {
    final res = await http.delete(Uri.parse('$_base$path'), headers: _headers);
    if (res.statusCode >= 400) throw ApiException(res.statusCode, res.body);
  }
}

class ApiException implements Exception {
  final int statusCode;
  final String body;
  ApiException(this.statusCode, this.body);
  @override
  String toString() => 'ApiException($statusCode): $body';
}
