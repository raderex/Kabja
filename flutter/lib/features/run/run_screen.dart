import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';
import '../../core/auth/auth_provider.dart';
import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';
import 'package:google_fonts/google_fonts.dart';

enum RunState { idle, running, paused, finished }

class RunScreen extends ConsumerStatefulWidget {
  const RunScreen({super.key});
  @override
  ConsumerState<RunScreen> createState() => _RunScreenState();
}

class _RunScreenState extends ConsumerState<RunScreen> {
  RunState _state = RunState.idle;
  String? _runId;
  DateTime? _startTime;
  Duration _elapsed = Duration.zero;
  double _distance = 0;
  double _pace = 0;
  StreamSubscription<Position>? _positionStream;
  LatLng? _lastPos;
  Timer? _updateTimer;
  Timer? _tickTimer;

  @override
  void dispose() {
    _positionStream?.cancel();
    _updateTimer?.cancel();
    _tickTimer?.cancel();
    super.dispose();
  }

  void _startRun() async {
    final auth = ref.read(authProvider);
    try {
      final res = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/run/start'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ${auth.token}',
        },
      );
      if (res.statusCode != 200) return;
      final data = jsonDecode(res.body);
      setState(() {
        _runId = data['run_id'];
        _startTime = DateTime.now();
        _state = RunState.running;
        _distance = 0;
        _pace = 0;
        _elapsed = Duration.zero;
      });
      _startGps();
      _startTick();
      _startUpdates();
    } catch (_) {}
  }

  void _startGps() {
    _positionStream = Geolocator.getPositionStream(
      locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high, distanceFilter: 3),
    ).listen((pos) {
      final current = LatLng(pos.latitude, pos.longitude);
      if (_lastPos != null) {
        _distance += Geolocator.distanceBetween(
          _lastPos!.latitude, _lastPos!.longitude,
          current.latitude, current.longitude,
        );
      }
      _lastPos = current;
      if (_distance > 0 && _elapsed.inSeconds > 0) {
        _pace = (_elapsed.inSeconds / 60) / (_distance / 1000);
      }
    });
  }

  void _startTick() {
    _tickTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_startTime == null) return;
      setState(() {
        _elapsed = DateTime.now().difference(_startTime!);
      });
    });
  }

  void _startUpdates() {
    _updateTimer = Timer.periodic(const Duration(seconds: 3), (_) async {
      if (_state != RunState.running || _lastPos == null || _runId == null) return;
      final auth = ref.read(authProvider);
      try {
        await http.post(
          Uri.parse('${AppConfig.apiBaseUrl}/api/run-update'),
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ${auth.token}',
          },
          body: jsonEncode({
            'run_id': _runId,
            'lat': _lastPos!.latitude,
            'lng': _lastPos!.longitude,
            'distance': _distance,
          }),
        );
      } catch (_) {}
    });
  }

  void _pauseRun() {
    _positionStream?.cancel();
    _updateTimer?.cancel();
    setState(() => _state = RunState.paused);
  }

  void _resumeRun() {
    _startGps();
    _startUpdates();
    setState(() => _state = RunState.running);
  }

  void _finishRun() async {
    _positionStream?.cancel();
    _updateTimer?.cancel();
    _tickTimer?.cancel();
    final auth = ref.read(authProvider);
    try {
      final res = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/run/finish'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ${auth.token}',
        },
        body: jsonEncode({
          'run_id': _runId,
          'distance': _distance,
          'elapsed_seconds': _elapsed.inSeconds,
        }),
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        if (mounted) _showResult(data);
      }
    } catch (_) {}
    setState(() => _state = RunState.finished);
  }

  void _showResult(Map<String, dynamic> data) {
    final captured = data['cells_captured'] ?? 0;
    showDialog(
      context: context,
      barrierColor: Colors.black87,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.hexagon, color: AppColors.accent, size: 48),
            const SizedBox(height: 16),
            Text('RUN COMPLETE',
                style: GoogleFonts.bebasNeue(
                    fontSize: 28, color: AppColors.textPrimary, letterSpacing: 2)),
            const SizedBox(height: 8),
            Text('$captured cells captured!',
                style: const TextStyle(
                    color: AppColors.success, fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text('${(_distance / 1000).toStringAsFixed(2)} km',
                style: GoogleFonts.bebasNeue(
                    fontSize: 36, color: AppColors.accent)),
            Text(_formatDuration(_elapsed),
                style: const TextStyle(color: AppColors.textSecondary, fontSize: 14)),
            const SizedBox(height: 24),
            ElevatedButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('NICE!'),
            ),
          ],
        ),
      ),
    );
  }

  String _formatDuration(Duration d) {
    final h = d.inHours.toString().padLeft(2, '0');
    final m = (d.inMinutes % 60).toString().padLeft(2, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    return '$h:$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            children: [
              const Spacer(flex: 2),
              Text(_formatDuration(_elapsed),
                  style: GoogleFonts.bebasNeue(
                      fontSize: 72, color: AppColors.textPrimary, letterSpacing: 2)),
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _Stat(label: 'DISTANCE',
                      value: '${(_distance / 1000).toStringAsFixed(2)} km'),
                  const SizedBox(width: 40),
                  _Stat(label: 'PACE',
                      value: _pace > 0
                          ? '${(_pace).toStringAsFixed(1)} min/km'
                          : '--'),
                ],
              ),
              const Spacer(flex: 2),
              if (_state == RunState.idle)
                _RunButton(
                  label: 'START',
                  color: AppColors.accent,
                  onTap: _startRun,
                )
              else if (_state == RunState.running) ...[
                _RunButton(
                  label: 'PAUSE',
                  color: AppColors.textSecondary,
                  onTap: _pauseRun,
                ),
                const SizedBox(height: 14),
                _RunButton(
                  label: 'FINISH',
                  color: AppColors.danger,
                  onTap: _finishRun,
                ),
              ] else if (_state == RunState.paused) ...[
                _RunButton(
                  label: 'RESUME',
                  color: AppColors.accent,
                  onTap: _resumeRun,
                ),
                const SizedBox(height: 14),
                _RunButton(
                  label: 'FINISH',
                  color: AppColors.danger,
                  onTap: _finishRun,
                ),
              ],
              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  const _Stat({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(value,
            style: GoogleFonts.bebasNeue(
                fontSize: 22, color: AppColors.accent)),
        Text(label,
            style: GoogleFonts.inter(
                fontSize: 10, color: AppColors.textSecondary, letterSpacing: 2)),
      ],
    );
  }
}

class _RunButton extends StatelessWidget {
  final String label;
  final Color color;
  final VoidCallback onTap;
  const _RunButton(
      {required this.label, required this.color, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 56,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: color,
          foregroundColor: Colors.black,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          elevation: 0,
        ),
        child: Text(label,
            style: GoogleFonts.bebasNeue(fontSize: 20, letterSpacing: 2)),
      ),
    );
  }
}
