import 'dart:async';
import 'dart:convert';
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
  LatLng _center = const LatLng(27.7172, 85.3240);
  List<String> _myCells = [];
  List<Map<String, dynamic>> _nearbyRunners = [];
  WebSocketChannel? _ws;
  StreamSubscription<Position>? _positionStream;
  bool _isMenuOpen = false;
  final h3 = H3Factory().load();

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
          _loadTerritory();
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
        final boundary = h3.h3ToGeoBoundary(BigInt.parse(cellId, radix: 16));
        final points = boundary.map((gp) => LatLng(gp.lat, gp.lon)).toList();
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
              MarkerLayer(
                markers: _nearbyRunners.map((r) => Marker(
                  point: LatLng(r['lat'] as double, r['lng'] as double),
                  width: 32, height: 32,
                  child: const RunningMarker(isOther: true),
                )).toList(),
              ),
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

          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _MapButton(
                    icon: Icons.menu,
                    onTap: () => setState(() => _isMenuOpen = !_isMenuOpen),
                  ),
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

          if (_isMenuOpen)
            HamburgerMenu(
              onClose: () => setState(() => _isMenuOpen = false),
              onNavigate: (route) {
                setState(() => _isMenuOpen = false);
                context.push(route);
              },
            ),

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
