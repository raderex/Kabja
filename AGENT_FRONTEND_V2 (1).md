# AGENT: Frontend Engineer — V2
> **Ship today. Test tonight.**
> You own: ALL Flutter code under `flutter/lib/`.
> The Flutter folder has ZERO Dart files. You are building from scratch.
> The backend is running. Wire up to it. Make it beautiful.

---

## Design brief

**Audience:** Young runners in Kathmandu. Think Strava meets a mobile game.
**Feel:** Dark theme. Amber/orange accent (`#EF9F27`). Clean. Fast. No clutter.
**Key rules:**
- App opens directly to the map — no splash, no login wall for the map
- Hamburger menu (top-left) replaces bottom nav — keeps the map full-screen
- The user's location is NOT a pin — it's an animated running figure icon
- Every button must work. No dead UI.
- Fonts: `Bebas Neue` for headings, `Inter` for body

**Color palette:**
```dart
static const background = Color(0xFF0A0A0A);    // near black
static const surface    = Color(0xFF1A1A1A);    // cards
static const accent     = Color(0xFFEF9F27);    // amber — primary CTA
static const accentDark = Color(0xFF8A5A0D);    // pressed state
static const textPrimary   = Color(0xFFFFFFFF);
static const textSecondary = Color(0xFF9A9A9A);
static const territory  = Color(0x55EF9F27);    // semi-transparent amber
static const territorial_border = Color(0xFFEF9F27);
static const danger     = Color(0xFFD85A30);    // stolen cells, destructive
static const success    = Color(0xFF1D9E75);    // cells gained
```

---

## Step 0 — pubspec.yaml

Replace the entire `dependencies:` block with:

```yaml
name: kabja
description: Run. Capture. Dominate.
publish_to: 'none'
version: 1.0.0+1

environment:
  sdk: '>=3.3.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter

  # State management
  flutter_riverpod: ^2.5.1
  riverpod_annotation: ^2.3.5

  # Navigation
  go_router: ^13.2.4

  # Maps
  flutter_map: ^7.0.2
  latlong2: ^0.9.1

  # Location
  geolocator: ^12.0.0

  # Networking
  http: ^1.2.1
  web_socket_channel: ^3.0.1

  # Storage
  flutter_secure_storage: ^9.2.2
  shared_preferences: ^2.3.2

  # Strava deep links
  app_links: ^6.3.2

  # H3 territory rendering
  h3_flutter: ^1.0.3

  # UI
  google_fonts: ^6.2.1
  shimmer: ^3.0.0
  cached_network_image: ^3.3.1
  lottie: ^3.1.2

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^4.0.0
  build_runner: ^2.4.9
  riverpod_generator: ^2.4.0

flutter:
  uses-material-design: true
  assets:
    - assets/animations/
    - assets/images/
```

Create asset folders:
```bash
mkdir -p flutter/assets/animations flutter/assets/images
```

Run:
```bash
flutter pub get
```

---

## Step 1 — `flutter/lib/main.dart`

```dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Full screen — hide status bar for immersive map experience
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
  ));
  SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);

  runApp(const ProviderScope(child: KabjaApp()));
}

class KabjaApp extends ConsumerWidget {
  const KabjaApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(appRouterProvider);
    return MaterialApp.router(
      title: 'Kabja',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.dark(),
      routerConfig: router,
    );
  }
}
```

---

## Step 2 — `flutter/lib/core/theme/app_theme.dart`

```dart
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  static const background    = Color(0xFF0A0A0A);
  static const surface       = Color(0xFF1A1A1A);
  static const surfaceHigh   = Color(0xFF252525);
  static const accent        = Color(0xFFEF9F27);
  static const accentDark    = Color(0xFF8A5A0D);
  static const textPrimary   = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF9A9A9A);
  static const territory     = Color(0x55EF9F27);
  static const territoryBorder = Color(0xFFEF9F27);
  static const danger        = Color(0xFFD85A30);
  static const success       = Color(0xFF1D9E75);
}

class AppTheme {
  static ThemeData dark() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: const ColorScheme.dark(
        primary: AppColors.accent,
        surface: AppColors.surface,
        onPrimary: Colors.black,
        onSurface: AppColors.textPrimary,
      ),
      textTheme: GoogleFonts.interTextTheme(ThemeData.dark().textTheme).copyWith(
        displayLarge: GoogleFonts.bebasNeue(
            fontSize: 48, color: AppColors.textPrimary, letterSpacing: 2),
        displayMedium: GoogleFonts.bebasNeue(
            fontSize: 36, color: AppColors.textPrimary, letterSpacing: 1.5),
        titleLarge: GoogleFonts.bebasNeue(
            fontSize: 24, color: AppColors.textPrimary, letterSpacing: 1),
        titleMedium: GoogleFonts.inter(
            fontSize: 16, fontWeight: FontWeight.w600, color: AppColors.textPrimary),
        bodyMedium: GoogleFonts.inter(fontSize: 14, color: AppColors.textSecondary),
        labelSmall: GoogleFonts.inter(
            fontSize: 10, letterSpacing: 1.5, color: AppColors.textSecondary,
            fontWeight: FontWeight.w500),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        iconTheme: IconThemeData(color: AppColors.textPrimary),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.accent,
          foregroundColor: Colors.black,
          minimumSize: const Size(double.infinity, 52),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          textStyle: GoogleFonts.bebasNeue(fontSize: 18, letterSpacing: 2),
        ),
      ),
    );
  }
}
```

---

## Step 3 — `flutter/lib/core/config/app_config.dart`

```dart
class AppConfig {
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL', defaultValue: 'http://10.0.2.2:8000');
  static const wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL', defaultValue: 'ws://10.0.2.2:8000');
  // 10.0.2.2 = localhost from Android emulator
  // For physical device on same WiFi: use your machine's IP e.g. 192.168.1.X
}
```

---

## Step 4 — `flutter/lib/core/auth/auth_provider.dart`

```dart
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
```

---

## Step 5 — `flutter/lib/core/network/api_client.dart`

```dart
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
```

---

## Step 6 — `flutter/lib/core/router/app_router.dart`

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../features/map/map_screen.dart';
import '../../features/auth/login_screen.dart';
import '../../features/auth/register_screen.dart';
import '../../features/run/run_screen.dart';
import '../../features/competition/competition_screen.dart';
import '../../features/profile/profile_screen.dart';
import '../auth/auth_provider.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final auth = ref.watch(authProvider);

  return GoRouter(
    initialLocation: '/map',
    redirect: (context, state) {
      // Map is public — no redirect needed
      // Auth-only routes redirect to login
      final authRequired = ['/run', '/profile'];
      if (authRequired.contains(state.matchedLocation) && !auth.isLoggedIn) {
        return '/login?from=${state.matchedLocation}';
      }
      return null;
    },
    routes: [
      GoRoute(path: '/map',         builder: (_, __) => const MapScreen()),
      GoRoute(path: '/run',          builder: (_, __) => const RunScreen()),
      GoRoute(path: '/competition',  builder: (_, __) => const CompetitionScreen()),
      GoRoute(path: '/profile',      builder: (_, __) => const ProfileScreen()),
      GoRoute(path: '/login',        builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/register',     builder: (_, __) => const RegisterScreen()),
    ],
  );
});
```

---

## Step 7 — `flutter/lib/features/auth/login_screen.dart`

```dart
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import '../../core/auth/auth_provider.dart';
import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';
import 'package:google_fonts/google_fonts.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _loading = false;
  String? _error;

  Future<void> _login() async {
    setState(() { _loading = true; _error = null; });
    try {
      final res = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'username': _userCtrl.text.trim(),
                          'password': _passCtrl.text}),
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        await ref.read(authProvider.notifier).setAuth(
          token: data['access_token'],
          userId: data['user_id'],
          username: data['username'],
          displayName: data['display_name'] ?? data['username'],
        );
        if (mounted) context.go('/map');
      } else {
        setState(() => _error = 'Wrong username or password');
      }
    } catch (e) {
      setState(() => _error = 'Connection error. Is the server running?');
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Spacer(),
              Text('KABJA', style: Theme.of(context).textTheme.displayLarge),
              Text('RUN. CAPTURE. DOMINATE.',
                  style: GoogleFonts.inter(
                      color: AppColors.accent, fontSize: 12, letterSpacing: 3)),
              const SizedBox(height: 48),
              _Field(ctrl: _userCtrl, label: 'Username', icon: Icons.person_outline),
              const SizedBox(height: 14),
              _Field(ctrl: _passCtrl, label: 'Password',
                  icon: Icons.lock_outline, obscure: true),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: AppColors.danger, fontSize: 13)),
              ],
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: _loading ? null : _login,
                child: _loading
                    ? const SizedBox(width: 20, height: 20,
                        child: CircularProgressIndicator(
                            color: Colors.black, strokeWidth: 2))
                    : const Text('LOGIN'),
              ),
              const SizedBox(height: 14),
              Center(
                child: TextButton(
                  onPressed: () => context.go('/register'),
                  child: Text("Don't have an account? Register",
                      style: TextStyle(color: AppColors.accent, fontSize: 13)),
                ),
              ),
              const Spacer(),
              Center(
                child: TextButton(
                  onPressed: () => context.go('/map'),
                  child: Text('Browse map without account',
                      style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  final TextEditingController ctrl;
  final String label;
  final IconData icon;
  final bool obscure;
  const _Field({required this.ctrl, required this.label,
      required this.icon, this.obscure = false});

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: ctrl,
      obscureText: obscure,
      style: const TextStyle(color: AppColors.textPrimary),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: AppColors.textSecondary),
        prefixIcon: Icon(icon, color: AppColors.textSecondary, size: 20),
        filled: true,
        fillColor: AppColors.surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AppColors.accent, width: 1.5),
        ),
      ),
    );
  }
}
```

Create `flutter/lib/features/auth/register_screen.dart` — same structure as login but calls `/api/auth/register` and has a `display_name` field. Same design. Connect it.

---

## Step 8 — `flutter/lib/features/map/map_screen.dart`

**This is the most important screen. App opens here.**

```dart
import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:go_router/go_router.dart';
import 'package:latlong2/latlong.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:h3_flutter/h3_flutter.dart';
import '../../core/auth/auth_provider.dart';
import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';
import '../../core/network/api_client.dart';
import 'package:http/http.dart' as http;
import 'widgets/hamburger_menu.dart';
import 'widgets/leaderboard_sheet.dart';
import 'widgets/running_marker.dart';

class MapScreen extends ConsumerStatefulWidget {
  const MapScreen({super.key});
  @override
  ConsumerState<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends ConsumerState<MapScreen> {
  final MapController _mapCtrl = MapController();
  LatLng? _myPosition;
  LatLng _center = const LatLng(27.7172, 85.3240); // Kathmandu default
  List<String> _myCells = [];
  List<Map<String, dynamic>> _nearbyRunners = [];
  WebSocketChannel? _ws;
  StreamSubscription<Position>? _positionStream;
  bool _isMenuOpen = false;
  final h3 = const H3();

  @override
  void initState() {
    super.initState();
    _initLocation();
    _loadTerritory();
    WidgetsBinding.instance.addPostFrameCallback((_) => _connectWs());
  }

  Future<void> _initLocation() async {
    LocationPermission perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
    }
    if (perm == LocationPermission.denied ||
        perm == LocationPermission.deniedForever) return;

    final pos = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high);
    setState(() {
      _myPosition = LatLng(pos.latitude, pos.longitude);
      _center = _myPosition!;
    });
    _mapCtrl.move(_center, 15);

    _positionStream = Geolocator.getPositionStream(
      locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high, distanceFilter: 5),
    ).listen((pos) {
      setState(() => _myPosition = LatLng(pos.latitude, pos.longitude));
    });
  }

  Future<void> _loadTerritory() async {
    final auth = ref.read(authProvider);
    if (auth.userId == null) return;
    try {
      final res = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/territory/${auth.userId}'),
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        setState(() => _myCells = List<String>.from(data['cells'] as List));
      }
    } catch (_) {}
  }

  void _connectWs() {
    final auth = ref.read(authProvider);
    if (auth.userId == null) return;
    _ws = WebSocketChannel.connect(
        Uri.parse('${AppConfig.wsBaseUrl}/ws/${auth.userId}'));
    _ws!.stream.listen((raw) {
      final msg = jsonDecode(raw as String) as Map<String, dynamic>;
      final type = msg['type'] as String;
      final payload = msg['payload'] as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        if (type == 'position') {
          final idx = _nearbyRunners
              .indexWhere((r) => r['run_id'] == payload['run_id']);
          if (idx >= 0) _nearbyRunners[idx] = payload;
          else _nearbyRunners.add(payload);
        }
        if (type == 'territory_result') {
          _loadTerritory(); // Refresh territory after a run finishes
          _showTerritoryResult(payload);
        }
      });
    });
  }

  void _showTerritoryResult(Map<String, dynamic> r) {
    final captured = r['cells_captured'] ?? 0;
    final lost = r['cells_lost'] ?? 0;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      backgroundColor: AppColors.surface,
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      content: Row(children: [
        const Icon(Icons.hexagon, color: AppColors.accent, size: 20),
        const SizedBox(width: 10),
        Text('+$captured cells claimed',
            style: const TextStyle(color: AppColors.success, fontWeight: FontWeight.bold)),
        if (lost > 0) ...[
          const SizedBox(width: 8),
          Text('  -$lost lost',
              style: const TextStyle(color: AppColors.danger, fontSize: 12)),
        ]
      ]),
    ));
  }

  List<Polygon> _buildTerritoryPolygons() {
    final polygons = <Polygon>[];
    for (final cellId in _myCells) {
      try {
        final boundary = h3.cellToBoundary(BigInt.parse(cellId, radix: 16));
        final points = boundary.map((gp) => LatLng(gp.lat, gp.lng)).toList();
        polygons.add(Polygon(
          points: points,
          color: AppColors.territory,
          borderColor: AppColors.territoryBorder,
          borderStrokeWidth: 1.2,
        ));
      } catch (_) {}
    }
    return polygons;
  }

  @override
  void dispose() {
    _ws?.sink.close();
    _positionStream?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);

    return Scaffold(
      extendBodyBehindAppBar: true,
      body: Stack(
        children: [
          // ── Full-screen map ──────────────────────────────────────────
          FlutterMap(
            mapController: _mapCtrl,
            options: MapOptions(
              initialCenter: _center,
              initialZoom: 15,
              maxZoom: 19,
              minZoom: 10,
            ),
            children: [
              TileLayer(
                urlTemplate:
                    'https://tiles.openfreemap.org/styles/liberty/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.kabja.app',
              ),
              PolygonLayer(polygons: _buildTerritoryPolygons()),
              // Nearby runners
              MarkerLayer(
                markers: _nearbyRunners.map((r) => Marker(
                  point: LatLng(r['lat'] as double, r['lng'] as double),
                  width: 32, height: 32,
                  child: const RunningMarker(isOther: true),
                )).toList(),
              ),
              // My position
              if (_myPosition != null)
                MarkerLayer(markers: [
                  Marker(
                    point: _myPosition!,
                    width: 40, height: 40,
                    child: const RunningMarker(isOther: false),
                  )
                ]),
            ],
          ),

          // ── Hamburger menu button — top left ─────────────────────────
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  // Menu button
                  _MapButton(
                    icon: Icons.menu,
                    onTap: () => setState(() => _isMenuOpen = !_isMenuOpen),
                  ),
                  // START RUN button — top right
                  if (auth.isLoggedIn)
                    GestureDetector(
                      onTap: () => context.push('/run'),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 18, vertical: 10),
                        decoration: BoxDecoration(
                          color: AppColors.accent,
                          borderRadius: BorderRadius.circular(24),
                          boxShadow: [
                            BoxShadow(
                              color: AppColors.accent.withOpacity(0.4),
                              blurRadius: 12, offset: const Offset(0, 4)),
                          ],
                        ),
                        child: Row(children: [
                          const Icon(Icons.play_arrow,
                              color: Colors.black, size: 18),
                          const SizedBox(width: 6),
                          Text('START RUN',
                              style: Theme.of(context)
                                  .textTheme
                                  .titleMedium
                                  ?.copyWith(
                                      color: Colors.black, fontSize: 13,
                                      letterSpacing: 1.5)),
                        ]),
                      ),
                    )
                  else
                    _MapButton(
                        icon: Icons.person_outline,
                        onTap: () => context.push('/login')),
                ],
              ),
            ),
          ),

          // ── Slide-out hamburger menu ─────────────────────────────────
          if (_isMenuOpen)
            HamburgerMenu(
              onClose: () => setState(() => _isMenuOpen = false),
              onNavigate: (route) {
                setState(() => _isMenuOpen = false);
                context.push(route);
              },
            ),

          // ── Locate me button — bottom right ──────────────────────────
          Positioned(
            bottom: 100, right: 16,
            child: Column(children: [
              _MapButton(
                icon: Icons.leaderboard,
                onTap: () => _showLeaderboard(),
              ),
              const SizedBox(height: 10),
              _MapButton(
                icon: Icons.my_location,
                onTap: () {
                  if (_myPosition != null) {
                    _mapCtrl.move(_myPosition!, 16);
                  }
                },
              ),
            ]),
          ),
        ],
      ),
    );
  }

  void _showLeaderboard() {
    final auth = ref.read(authProvider);
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => LeaderboardSheet(token: auth.token ?? ''),
    );
  }
}

class _MapButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;
  const _MapButton({required this.icon, required this.onTap});

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: Container(
          width: 44, height: 44,
          decoration: BoxDecoration(
            color: AppColors.surface.withOpacity(0.92),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
                color: Colors.white.withOpacity(0.08), width: .5),
          ),
          child: Icon(icon, color: AppColors.textPrimary, size: 22),
        ),
      );
}
```

---

## Step 9 — `flutter/lib/features/map/widgets/running_marker.dart`

The animated running figure. This replaces the boring pin.

```dart
import 'package:flutter/material.dart';
import '../../../core/theme/app_theme.dart';

class RunningMarker extends StatefulWidget {
  final bool isOther;
  const RunningMarker({super.key, required this.isOther});

  @override
  State<RunningMarker> createState() => _RunningMarkerState();
}

class _RunningMarkerState extends State<RunningMarker>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _bounce;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 600))
      ..repeat(reverse: true);
    _bounce = Tween<double>(begin: 0, end: -6).animate(
        CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut));
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = widget.isOther ? Colors.blue : AppColors.accent;

    return AnimatedBuilder(
      animation: _bounce,
      builder: (_, __) => Transform.translate(
        offset: Offset(0, _bounce.value),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Running figure
            Container(
              width: widget.isOther ? 28 : 36,
              height: widget.isOther ? 28 : 36,
              decoration: BoxDecoration(
                color: color,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: color.withOpacity(0.5),
                    blurRadius: 8, spreadRadius: 2,
                  )
                ],
              ),
              child: Center(
                child: Text(
                  '🏃',
                  style: TextStyle(fontSize: widget.isOther ? 14 : 18),
                ),
              ),
            ),
            // Drop shadow triangle
            CustomPaint(
              size: const Size(10, 5),
              painter: _TrianglePainter(color: color),
            ),
          ],
        ),
      ),
    );
  }
}

class _TrianglePainter extends CustomPainter {
  final Color color;
  _TrianglePainter({required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = color;
    final path = Path()
      ..moveTo(0, 0)
      ..lineTo(size.width / 2, size.height)
      ..lineTo(size.width, 0)
      ..close();
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(_) => false;
}
```

---

## Step 10 — `flutter/lib/features/map/widgets/hamburger_menu.dart`

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/auth/auth_provider.dart';
import '../../../core/theme/app_theme.dart';
import 'package:google_fonts/google_fonts.dart';

class HamburgerMenu extends ConsumerWidget {
  final VoidCallback onClose;
  final void Function(String route) onNavigate;

  const HamburgerMenu({
      super.key, required this.onClose, required this.onNavigate});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);

    return GestureDetector(
      onTap: onClose,
      child: Container(
        color: Colors.black54,
        child: Align(
          alignment: Alignment.topLeft,
          child: GestureDetector(
            onTap: () {}, // Prevent close when tapping menu itself
            child: Container(
              width: 280,
              height: double.infinity,
              color: AppColors.surface,
              child: SafeArea(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Header
                    Padding(
                      padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('KABJA',
                              style: GoogleFonts.bebasNeue(
                                  color: AppColors.accent,
                                  fontSize: 28, letterSpacing: 3)),
                          IconButton(
                            icon: const Icon(Icons.close,
                                color: AppColors.textSecondary),
                            onPressed: onClose,
                          ),
                        ],
                      ),
                    ),
                    if (auth.isLoggedIn) ...[
                      Padding(
                        padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
                        child: Text(auth.displayName ?? auth.username ?? '',
                            style: const TextStyle(
                                color: AppColors.textSecondary, fontSize: 13)),
                      ),
                    ] else ...[
                      const SizedBox(height: 8),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        child: ElevatedButton(
                          onPressed: () => onNavigate('/login'),
                          style: ElevatedButton.styleFrom(
                              minimumSize: const Size(double.infinity, 44)),
                          child: const Text('LOGIN / REGISTER'),
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    const Divider(color: AppColors.surfaceHigh, height: 1),
                    const SizedBox(height: 8),
                    _MenuItem(icon: Icons.map_outlined,
                        label: 'Map', onTap: () => onNavigate('/map')),
                    if (auth.isLoggedIn)
                      _MenuItem(icon: Icons.directions_run,
                          label: 'Start Run', onTap: () => onNavigate('/run')),
                    _MenuItem(icon: Icons.emoji_events_outlined,
                        label: 'Competitions',
                        onTap: () => onNavigate('/competition')),
                    if (auth.isLoggedIn)
                      _MenuItem(icon: Icons.person_outline,
                          label: 'Profile', onTap: () => onNavigate('/profile')),
                    const Spacer(),
                    const Divider(color: AppColors.surfaceHigh, height: 1),
                    if (auth.isLoggedIn)
                      _MenuItem(
                        icon: Icons.logout,
                        label: 'Logout',
                        color: AppColors.danger,
                        onTap: () {
                          ref.read(authProvider.notifier).logout();
                          onClose();
                        },
                      ),
                    const SizedBox(height: 20),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _MenuItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color? color;
  const _MenuItem(
      {required this.icon, required this.label,
       required this.onTap, this.color});

  @override
  Widget build(BuildContext context) => ListTile(
        leading: Icon(icon, color: color ?? AppColors.textSecondary, size: 22),
        title: Text(label,
            style: TextStyle(
                color: color ?? AppColors.textPrimary,
                fontSize: 15, fontWeight: FontWeight.w500)),
        onTap: onTap,
        dense: true,
      );
}
```

---

## Step 11 — Run screen, Competition screen, Profile screen

Create these three screens following the same dark theme. Key points per screen:

### `flutter/lib/features/run/run_screen.dart`
- Full black screen with large stats (Bebas Neue font)
- START → amber button. PAUSE → grey. FINISH → red
- After finish: modal shows cells captured (from WS territory_result)
- Background GPS must keep working when screen is off
- Wire to: `POST /api/run/start`, `POST /api/run-update` every 3s, `POST /api/run/finish`

### `flutter/lib/features/competition/competition_screen.dart`
- Prize image carousel (PageView)
- Countdown timer updating every second
- "Your territory: X km²" chip
- Wire to: `GET /api/competitions`

### `flutter/lib/features/profile/profile_screen.dart`
- Stats cards: total km², total runs, streak, cells owned
- Strava section: Connect button → opens browser OAuth → returns via deep link
- Wire to: `GET /api/profile/{user_id}`, `GET /api/strava/auth-url`, `GET /api/strava/status`, `DELETE /api/strava/disconnect`

### `flutter/lib/features/map/widgets/leaderboard_sheet.dart`
- DraggableScrollableSheet
- ListView of rank, name, km²
- Wire to: `GET /api/leaderboard`

---

## Step 12 — AndroidManifest.xml — required for GPS + deep links

Open `flutter/android/app/src/main/AndroidManifest.xml`. Ensure these exist:

```xml
<!-- Inside <manifest> tag -->
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.INTERNET" />

<!-- Inside <activity> tag — for Strava deep link -->
<intent-filter android:autoVerify="true">
    <action android:name="android.intent.action.VIEW" />
    <category android:name="android.intent.category.DEFAULT" />
    <category android:name="android.intent.category.BROWSABLE" />
    <data android:scheme="kabja" />
</intent-filter>
```

---

## Step 13 — Final run

```bash
cd flutter
flutter pub get
flutter analyze      # fix all errors (warnings OK)
flutter run          # on emulator or physical device
```

**On first launch you should see:**
- Map of Kathmandu loads immediately
- Hamburger icon top-left works → menu slides in
- Login/Register from menu works
- After login: START RUN button appears top-right
- Map shows territory polygons if user has any
- Animated running figure at user's GPS location

---

## Deliverables checklist

```
□ App launches directly to map (no splash screen)
□ Map tiles load (OpenFreeMap, Kathmandu centred)
□ Animated running figure at user's location (not a pin)
□ Hamburger menu opens/closes from top-left
□ Menu contains: Map, Start Run, Competitions, Profile, Login/Logout
□ Login screen works → JWT stored → redirects to map
□ Register screen works → creates account → redirects to map
□ START RUN button appears when logged in
□ Run screen shows live stats (distance, pace, time)
□ Run finish shows cells captured modal
□ Territory polygons render on map after run
□ Leaderboard bottom sheet opens from map
□ Competition screen loads prize + countdown
□ Profile screen shows stats + Strava connect button
□ flutter analyze returns 0 errors
```

---

*Frontend Engineer — Kabja V2 — 2026-06-02*
