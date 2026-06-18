import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class AuthState {
  final String? token;
  final String? userId;
  final String? username;
  final String? displayName;

  const AuthState({this.token, this.userId, this.username, this.displayName});

  bool get isLoggedIn => token != null && userId != null;

  AuthState copyWith({String? token, String? userId, String? username, String? displayName}) =>
      AuthState(
        token: token ?? this.token,
        userId: userId ?? this.userId,
        username: username ?? this.username,
        displayName: displayName ?? this.displayName,
      );
}

class AuthNotifier extends StateNotifier<AuthState> {
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  AuthNotifier() : super(const AuthState()) {
    _loadFromStorage();
  }

  Future<void> _loadFromStorage() async {
    final token = await _storage.read(key: 'token');
    final userId = await _storage.read(key: 'user_id');
    final username = await _storage.read(key: 'username');
    final displayName = await _storage.read(key: 'display_name');
    if (token != null && userId != null) {
      state = AuthState(token: token, userId: userId,
          username: username, displayName: displayName);
    }
  }

  Future<void> setAuth({
    required String token,
    required String userId,
    required String username,
    required String displayName,
  }) async {
    await _storage.write(key: 'token', value: token);
    await _storage.write(key: 'user_id', value: userId);
    await _storage.write(key: 'username', value: username);
    await _storage.write(key: 'display_name', value: displayName);
    state = AuthState(token: token, userId: userId,
        username: username, displayName: displayName);
  }

  Future<void> logout() async {
    await _storage.deleteAll();
    state = const AuthState();
  }
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>(
    (_) => AuthNotifier());
