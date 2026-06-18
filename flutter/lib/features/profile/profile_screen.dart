import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import '../../core/auth/auth_provider.dart';
import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';
import 'package:google_fonts/google_fonts.dart';

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});
  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  Map<String, dynamic>? _profile;
  bool _loading = true;
  bool _stravaConnected = false;
  bool _stravaLoading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final auth = ref.read(authProvider);
    if (auth.userId == null) return;

    try {
      final res = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/profile/${auth.userId}'),
        headers: {'Authorization': 'Bearer ${auth.token}'},
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        setState(() {
          _profile = data;
          _loading = false;
        });
      }
    } catch (_) {
      setState(() => _loading = false);
    }

    try {
      final stravaRes = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/strava/status'),
        headers: {'Authorization': 'Bearer ${auth.token}'},
      );
      if (stravaRes.statusCode == 200) {
        final sData = jsonDecode(stravaRes.body);
        setState(() => _stravaConnected = sData['connected'] ?? false);
      }
    } catch (_) {}
  }

  Future<void> _connectStrava() async {
    setState(() => _stravaLoading = true);
    final auth = ref.read(authProvider);
    try {
      final res = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/strava/auth-url'),
        headers: {'Authorization': 'Bearer ${auth.token}'},
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        data['url'] as String;
      }
    } catch (_) {}
    setState(() => _stravaLoading = false);
  }

  Future<void> _disconnectStrava() async {
    final auth = ref.read(authProvider);
    try {
      await http.delete(
        Uri.parse('${AppConfig.apiBaseUrl}/api/strava/disconnect'),
        headers: {'Authorization': 'Bearer ${auth.token}'},
      );
      setState(() => _stravaConnected = false);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);

    if (!auth.isLoggedIn) {
      return Scaffold(
        backgroundColor: AppColors.background,
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.person_outline, color: AppColors.textSecondary, size: 64),
              const SizedBox(height: 16),
              const Text('Login to view profile',
                  style: TextStyle(color: AppColors.textSecondary)),
              const SizedBox(height: 20),
              ElevatedButton(
                onPressed: () => context.go('/login'),
                child: const Text('LOGIN'),
              ),
            ],
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: Text('PROFILE',
            style: GoogleFonts.bebasNeue(
                fontSize: 22, color: AppColors.textPrimary, letterSpacing: 2)),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppColors.accent))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const SizedBox(height: 8),
                Center(
                  child: CircleAvatar(
                    radius: 40,
                    backgroundColor: AppColors.accent.withOpacity(0.2),
                    child: Text(
                      (auth.displayName ?? auth.username ?? '?')
                          .substring(0, 1)
                          .toUpperCase(),
                      style: GoogleFonts.bebasNeue(
                          fontSize: 36, color: AppColors.accent),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                Center(
                  child: Text(
                    auth.displayName ?? auth.username ?? '',
                    style: GoogleFonts.bebasNeue(
                        fontSize: 28, color: AppColors.textPrimary, letterSpacing: 1),
                  ),
                ),
                Center(
                  child: Text(
                    '@${auth.username ?? ''}',
                    style: const TextStyle(
                        color: AppColors.textSecondary, fontSize: 13),
                  ),
                ),
                const SizedBox(height: 28),
                Row(
                  children: [
                    _StatCard(
                      label: 'TOTAL km\u00B2',
                      value: '${_profile?['total_km2'] ?? 0}',
                      icon: Icons.hexagon,
                    ),
                    const SizedBox(width: 12),
                    _StatCard(
                      label: 'RUNS',
                      value: '${_profile?['total_runs'] ?? 0}',
                      icon: Icons.directions_run,
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    _StatCard(
                      label: 'STREAK',
                      value: '${_profile?['streak'] ?? 0} days',
                      icon: Icons.local_fire_department,
                    ),
                    const SizedBox(width: 12),
                    _StatCard(
                      label: 'CELLS',
                      value: '${_profile?['cells_owned'] ?? 0}',
                      icon: Icons.grid_on,
                    ),
                  ],
                ),
                const SizedBox(height: 28),
                const Divider(color: AppColors.surfaceHigh, height: 1),
                const SizedBox(height: 16),
                Text('STRAVA',
                    style: GoogleFonts.inter(
                        fontSize: 12, color: AppColors.textSecondary,
                        letterSpacing: 2)),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: AppColors.surface,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.directions_bike,
                          color: AppColors.accent, size: 28),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Text(
                          _stravaConnected
                              ? 'Strava connected'
                              : 'Connect Strava to import your runs',
                          style: const TextStyle(
                              color: AppColors.textPrimary, fontSize: 14),
                        ),
                      ),
                      if (_stravaConnected)
                        TextButton(
                          onPressed: _disconnectStrava,
                          child: const Text('Disconnect',
                              style: TextStyle(color: AppColors.danger, fontSize: 12)),
                        )
                      else
                        TextButton(
                          onPressed: _stravaLoading ? null : _connectStrava,
                          child: const Text('Connect',
                              style: TextStyle(color: AppColors.accent)),
                        ),
                    ],
                  ),
                ),
              ],
            ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;
  const _StatCard({
    required this.label, required this.value, required this.icon});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: AppColors.accent, size: 22),
            const SizedBox(height: 10),
            Text(value,
                style: GoogleFonts.bebasNeue(
                    fontSize: 28, color: AppColors.textPrimary)),
            Text(label,
                style: GoogleFonts.inter(
                    fontSize: 10, color: AppColors.textSecondary,
                    letterSpacing: 1.5)),
          ],
        ),
      ),
    );
  }
}
