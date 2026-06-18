## System Prompt

You are a **senior Flutter/mobile engineer** with 8+ years in mobile development and 4+ years specialising in Flutter/Dart. You have shipped multiple apps to the App Store and Play Store. You are known for building **premium, polished UIs** that feel native and delightful. You obsess over:

- **UI/UX craft**: Every screen must feel premium — not a "developer UI". Use glassmorphism, subtle gradients, micro-animations, and thoughtful spacing. Loading states use shimmer skeletons, not spinners. Tap targets have haptic feedback. Transitions are smooth (300ms ease-out). Empty states have illustrations and helpful text, never just blank space.
- **Design system consistency**: ALL colours come from `AppColors`. ALL text styles use `GoogleFonts.inter()`. ALL border radiuses are 12-20px. ALL cards have consistent padding (16-20px). Never use raw `Colors.blue` or default text styles.
- **State management**: Use Riverpod correctly — `StateNotifier` + `StateNotifierProvider` for mutable state, `Provider` for services, `FutureProvider` for async data. Never put business logic in widgets. Never call `ref.read` inside `build()` for state — use `ref.watch`.
- **Architecture**: Feature-based folder structure (`features/{feature}/`). Separate data layer (`core/network/`) from presentation. No god-widgets — break large widgets into private `_WidgetName` classes in the same file.
- **Platform handling**: Always check `context.mounted` after async gaps. Handle permissions gracefully (location, notifications). Support both Android and iOS deep links. Test on both platforms.
- **Performance**: Use `const` constructors everywhere possible. Use `IndexedStack` for tab persistence (already done). Avoid rebuilding the entire widget tree — use targeted `Consumer` widgets or `select()`.
- **Animations**: Use `flutter_animate` for declarative animations. Use `AnimatedContainer` / `AnimatedOpacity` for state-driven transitions. Use `TweenAnimationBuilder` for number counters. Keep animations under 400ms — fast enough to feel snappy, slow enough to be noticed.

**Your working style:**
1. Read ALL referenced files before writing a single line
2. Match the existing code style exactly — same import order, same naming conventions, same widget patterns
3. After creating a new file, verify it compiles with `flutter analyze` (no red squiggles)
4. Run the app on a device/emulator and visually verify every screen you touch
5. If a design decision is ambiguous, choose the more premium/polished option
6. NEVER modify files outside your ownership boundary

**Ownership boundary — you own:**
- Everything under `flutter/` — all Dart code, pubspec.yaml, platform configs
- `flutter/lib/main.dart` — app entry, router, theme, bottom nav
- `flutter/lib/core/` — auth, config, network, map, strava providers
- `flutter/lib/features/` — all feature screens and widgets
- `flutter/android/` and `flutter/ios/` — platform-specific configs (manifest, Info.plist)

**You do NOT touch:**
- `backend/` — Backend and Realtime Engineers own this
- `docker-compose.yml`, `nginx/`, `.env`
- Any Python file

**Design reference:** The app should feel like INTVL (https://www.intvl.com.au) — dark, premium, sport-tech aesthetic. Think Nike Run Club meets territory strategy game. Amber/gold accent on deep black. Modern typography. Glassmorphism cards. Pulsing animations for active states.

---

# AGENT: Frontend Engineer — Strava Integration + Modern UI/UX
> **Deliver today. Tests tomorrow morning.**
> You own: ALL Flutter code under `flutter/`.
> Do NOT touch: backend Python files, Docker Compose, Nginx, Redis logic.

---

## Your context (read once, then start coding)

Kabja is a territory running app. We're adding **Strava integration** so users can connect their Strava account from within the app and auto-import activities. You also need to **modernize the UI/UX** across the app.

**What Backend Engineer is building (you depend on these APIs):**
```
GET  /api/strava/auth-url       → { "auth_url": "https://www.strava.com/oauth/authorize?..." }
GET  /api/strava/status         → { "connected": true/false, "profile": {...}, "imported_activities": N }
POST /api/strava/sync           → { "imported": N, "skipped": N, "total_cells": N }
DELETE /api/strava/disconnect   → { "ok": true }
GET  /api/strava/sync-status    → { "syncing": true/false }
```

**WebSocket messages (from Realtime Engineer):**
```json
{ "type": "strava_sync", "payload": { "activity_name": "...", "cells_captured": N, "km2_captured": 0.0, "source": "strava" } }
{ "type": "strava_sync_status", "payload": { "status": "syncing" | "complete", ... } }
```

**Deep link scheme:** `kabja://strava-callback?success=true&athlete_id=...`
The backend redirects to this after OAuth. Your app must handle this deep link.

---

## Step 0 — Read these files first

```
flutter/pubspec.yaml
flutter/lib/main.dart                          ← router, theme, _HomeShell
flutter/lib/core/auth/auth_provider.dart       ← current auth state
flutter/lib/core/network/run_repository.dart   ← existing API calls
flutter/lib/core/config/app_config.dart        ← base URLs
flutter/lib/features/run/run_screen.dart       ← run screen
flutter/lib/features/competition/competition_screen.dart
```

---

## Step 1 — Update `flutter/pubspec.yaml`

Add these dependencies:

```yaml
dependencies:
  # existing deps stay — add only what's missing:
  url_launcher: ^6.3.0          # already present — confirm
  app_links: ^6.3.2             # deep link handling for Strava callback
  cached_network_image: ^3.4.1  # Strava profile pics
  shimmer: ^3.0.0               # loading skeletons for modern UI
  lottie: ^3.1.2                # micro-animations
  fl_chart: ^0.69.0             # stats charts in profile
```

Run:
```bash
flutter pub get
```

---

## Step 2 — Create `flutter/lib/core/network/strava_repository.dart`

```dart
// flutter/lib/core/network/strava_repository.dart
import 'dart:convert';
import 'package:dio/dio.dart';
import '../config/app_config.dart';

class StravaRepository {
  final String _base = AppConfig.apiBaseUrl;
  final String Function() _getToken;

  StravaRepository({required String Function() getToken}) : _getToken = getToken;

  Dio get _dio => Dio(BaseOptions(
    baseUrl: _base,
    headers: {
      'Authorization': 'Bearer ${_getToken()}',
      'Content-Type': 'application/json',
    },
    connectTimeout: const Duration(seconds: 15),
    receiveTimeout: const Duration(seconds: 30),
  ));

  /// Get the Strava OAuth authorization URL
  Future<String> getAuthUrl() async {
    final resp = await _dio.get('/api/strava/auth-url');
    return resp.data['auth_url'] as String;
  }

  /// Check Strava connection status
  Future<Map<String, dynamic>> getStatus() async {
    final resp = await _dio.get('/api/strava/status');
    return resp.data as Map<String, dynamic>;
  }

  /// Trigger manual activity sync
  Future<Map<String, dynamic>> syncActivities() async {
    final resp = await _dio.post('/api/strava/sync');
    return resp.data as Map<String, dynamic>;
  }

  /// Disconnect Strava
  Future<void> disconnect() async {
    await _dio.delete('/api/strava/disconnect');
  }

  /// Check if sync is currently running
  Future<bool> isSyncing() async {
    final resp = await _dio.get('/api/strava/sync-status');
    return resp.data['syncing'] == true;
  }
}
```

---

## Step 3 — Create Strava provider

Create `flutter/lib/core/strava/strava_provider.dart`:

```dart
// flutter/lib/core/strava/strava_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_provider.dart';
import '../network/strava_repository.dart';

// ── Repository provider ──
final stravaRepoProvider = Provider<StravaRepository>((ref) {
  final auth = ref.watch(authProvider);
  return StravaRepository(
    getToken: () => auth.token ?? '',
  );
});

// ── Strava connection state ──
class StravaState {
  final bool isConnected;
  final bool isSyncing;
  final bool isLoading;
  final String? error;
  final Map<String, dynamic>? profile;
  final int importedActivities;

  const StravaState({
    this.isConnected = false,
    this.isSyncing = false,
    this.isLoading = true,
    this.error,
    this.profile,
    this.importedActivities = 0,
  });

  StravaState copyWith({
    bool? isConnected,
    bool? isSyncing,
    bool? isLoading,
    String? error,
    Map<String, dynamic>? profile,
    int? importedActivities,
  }) => StravaState(
    isConnected: isConnected ?? this.isConnected,
    isSyncing: isSyncing ?? this.isSyncing,
    isLoading: isLoading ?? this.isLoading,
    error: error,
    profile: profile ?? this.profile,
    importedActivities: importedActivities ?? this.importedActivities,
  );
}

class StravaNotifier extends StateNotifier<StravaState> {
  final StravaRepository _repo;

  StravaNotifier(this._repo) : super(const StravaState()) {
    loadStatus();
  }

  Future<void> loadStatus() async {
    state = state.copyWith(isLoading: true);
    try {
      final status = await _repo.getStatus();
      state = StravaState(
        isConnected: status['connected'] == true,
        isLoading: false,
        profile: status['profile'] as Map<String, dynamic>?,
        importedActivities: status['imported_activities'] as int? ?? 0,
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<String> getAuthUrl() async {
    return await _repo.getAuthUrl();
  }

  Future<Map<String, dynamic>> syncActivities() async {
    state = state.copyWith(isSyncing: true, error: null);
    try {
      final result = await _repo.syncActivities();
      await loadStatus(); // refresh state after sync
      state = state.copyWith(isSyncing: false);
      return result;
    } catch (e) {
      state = state.copyWith(isSyncing: false, error: e.toString());
      rethrow;
    }
  }

  Future<void> disconnect() async {
    try {
      await _repo.disconnect();
      state = const StravaState(isConnected: false, isLoading: false);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  /// Called when WS receives strava_sync_status message
  void onSyncStatusUpdate(Map<String, dynamic> payload) {
    final status = payload['status'] as String?;
    if (status == 'syncing') {
      state = state.copyWith(isSyncing: true);
    } else if (status == 'complete') {
      state = state.copyWith(isSyncing: false);
      loadStatus(); // refresh imported count
    }
  }

  /// Called when WS receives strava_sync (individual activity imported)
  void onActivityImported(Map<String, dynamic> payload) {
    state = state.copyWith(
      importedActivities: state.importedActivities + 1,
    );
  }
}

final stravaProvider = StateNotifierProvider<StravaNotifier, StravaState>((ref) {
  final repo = ref.watch(stravaRepoProvider);
  return StravaNotifier(repo);
});
```

---

## Step 4 — Create `flutter/lib/features/profile/profile_screen.dart`

This is a NEW screen — the user's profile with Strava integration. **Make it premium and modern.**

Design requirements:
- **Dark theme** matching `AppColors` palette (deep black background, amber accents)
- **Glassmorphism cards** with subtle border glow
- **Strava section** with Connect/Disconnect button, profile pic, sync button
- **Stats overview** with animated counters
- **Shimmer loading** states
- **Strava brand colors** (#FC4C02 orange) for the Connect button

```dart
// flutter/lib/features/profile/profile_screen.dart
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:cached_network_image/cached_network_image.dart';
import 'package:shimmer/shimmer.dart';
import '../../main.dart';  // AppColors
import '../../core/auth/auth_provider.dart';
import '../../core/strava/strava_provider.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final strava = ref.watch(stravaProvider);
    final stravaNotifier = ref.read(stravaProvider.notifier);

    return Scaffold(
      backgroundColor: AppColors.background,
      body: CustomScrollView(
        physics: const BouncingScrollPhysics(),
        slivers: [
          // ── App Bar ──
          SliverAppBar(
            expandedHeight: 120,
            floating: false,
            pinned: true,
            backgroundColor: AppColors.background,
            flexibleSpace: FlexibleSpaceBar(
              title: Text('Profile',
                style: GoogleFonts.inter(
                  fontWeight: FontWeight.w800,
                  fontSize: 22,
                  color: AppColors.textPrimary,
                )),
              centerTitle: true,
            ),
            actions: [
              IconButton(
                icon: const Icon(Icons.logout_rounded, color: AppColors.textSecondary),
                onPressed: () => ref.read(authProvider.notifier).logout(),
              ),
            ],
          ),

          SliverPadding(
            padding: const EdgeInsets.all(20),
            sliver: SliverList(
              delegate: SliverChildListDelegate([
                // ── User Info Card ──
                _GlassCard(
                  child: Row(
                    children: [
                      // Avatar
                      Container(
                        width: 64, height: 64,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: const LinearGradient(
                            colors: [AppColors.accent, AppColors.accentDark],
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: AppColors.accent.withValues(alpha: 0.3),
                              blurRadius: 16,
                              spreadRadius: 2,
                            ),
                          ],
                        ),
                        child: Center(
                          child: Text(
                            (auth.username ?? '?')[0].toUpperCase(),
                            style: GoogleFonts.inter(
                              fontSize: 28, fontWeight: FontWeight.w900,
                              color: Colors.black,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              auth.username ?? 'Runner',
                              style: GoogleFonts.inter(
                                fontSize: 20, fontWeight: FontWeight.w700,
                                color: AppColors.textPrimary,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
                              decoration: BoxDecoration(
                                color: AppColors.accent.withValues(alpha: 0.15),
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: Text(
                                auth.role?.toUpperCase() ?? 'RUNNER',
                                style: GoogleFonts.inter(
                                  fontSize: 10, fontWeight: FontWeight.w700,
                                  color: AppColors.accent, letterSpacing: 1.5,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 20),

                // ── Strava Integration Card ──
                _StravaCard(strava: strava, notifier: stravaNotifier),

                const SizedBox(height: 20),

                // ── Quick Stats ──
                _StatsGrid(),

                const SizedBox(height: 20),

                // ── App Info ──
                _GlassCard(
                  child: Column(
                    children: [
                      _InfoRow(icon: Icons.hexagon_rounded, label: 'Version', value: '4.0.0'),
                      const Divider(color: AppColors.border, height: 24),
                      _InfoRow(icon: Icons.map_rounded, label: 'Region', value: 'Nepal 🇳🇵'),
                      const Divider(color: AppColors.border, height: 24),
                      _InfoRow(icon: Icons.hexagon_outlined, label: 'H3 Resolution', value: '10'),
                    ],
                  ),
                ),
              ]),
            ),
          ),
        ],
      ),
    );
  }
}


// ── Strava Integration Card ──────────────────────────────────────────────────

class _StravaCard extends StatelessWidget {
  final StravaState strava;
  final StravaNotifier notifier;

  const _StravaCard({required this.strava, required this.notifier});

  static const stravaOrange = Color(0xFFFC4C02);

  @override
  Widget build(BuildContext context) {
    if (strava.isLoading) {
      return _GlassCard(
        child: Shimmer.fromColors(
          baseColor: AppColors.surfaceHigh,
          highlightColor: AppColors.border,
          child: Container(height: 80, decoration: BoxDecoration(
            color: AppColors.surfaceHigh,
            borderRadius: BorderRadius.circular(12),
          )),
        ),
      );
    }

    return _GlassCard(
      borderColor: strava.isConnected ? stravaOrange.withValues(alpha: 0.4) : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Row(
            children: [
              // Strava icon (use text since we don't have the SVG)
              Container(
                width: 40, height: 40,
                decoration: BoxDecoration(
                  color: stravaOrange.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Center(
                  child: Text('S', style: TextStyle(
                    color: stravaOrange, fontSize: 22, fontWeight: FontWeight.w900,
                  )),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Strava', style: GoogleFonts.inter(
                      fontSize: 16, fontWeight: FontWeight.w700,
                      color: AppColors.textPrimary,
                    )),
                    Text(
                      strava.isConnected ? 'Connected' : 'Not connected',
                      style: GoogleFonts.inter(
                        fontSize: 12,
                        color: strava.isConnected ? AppColors.success : AppColors.textMuted,
                      ),
                    ),
                  ],
                ),
              ),
              // Status indicator
              Container(
                width: 10, height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: strava.isConnected ? AppColors.success : AppColors.textMuted,
                  boxShadow: strava.isConnected ? [
                    BoxShadow(
                      color: AppColors.success.withValues(alpha: 0.5),
                      blurRadius: 8,
                    ),
                  ] : null,
                ),
              ),
            ],
          ),

          if (strava.isConnected) ...[
            const SizedBox(height: 16),

            // Profile info
            if (strava.profile != null) ...[
              Row(
                children: [
                  if (strava.profile!['profile_pic'] != null &&
                      (strava.profile!['profile_pic'] as String).isNotEmpty)
                    ClipRRect(
                      borderRadius: BorderRadius.circular(20),
                      child: CachedNetworkImage(
                        imageUrl: strava.profile!['profile_pic'],
                        width: 40, height: 40,
                        fit: BoxFit.cover,
                        placeholder: (_, __) => Container(
                          width: 40, height: 40,
                          color: AppColors.surfaceHigh,
                        ),
                      ),
                    ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      '${strava.profile!['firstname'] ?? ''} ${strava.profile!['lastname'] ?? ''}'.trim(),
                      style: GoogleFonts.inter(
                        fontSize: 14, color: AppColors.textSecondary,
                      ),
                    ),
                  ),
                  // Imported count badge
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: stravaOrange.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      '${strava.importedActivities} synced',
                      style: GoogleFonts.inter(
                        fontSize: 11, fontWeight: FontWeight.w600,
                        color: stravaOrange,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
            ],

            // Action buttons
            Row(
              children: [
                Expanded(
                  child: _StravaButton(
                    label: strava.isSyncing ? 'Syncing...' : 'Sync Now',
                    icon: strava.isSyncing ? Icons.sync_rounded : Icons.sync_rounded,
                    color: stravaOrange,
                    isLoading: strava.isSyncing,
                    onTap: strava.isSyncing ? null : () async {
                      try {
                        final result = await notifier.syncActivities();
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                            content: Text('Imported ${result['imported']} activities, '
                                '${result['total_cells']} cells captured!'),
                            backgroundColor: AppColors.success,
                          ));
                        }
                      } catch (_) {
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                            content: Text('Sync failed. Check your connection.'),
                            backgroundColor: AppColors.danger,
                          ));
                        }
                      }
                    },
                  ),
                ),
                const SizedBox(width: 12),
                _StravaButton(
                  label: 'Disconnect',
                  icon: Icons.link_off_rounded,
                  color: AppColors.danger,
                  onTap: () => _confirmDisconnect(context, notifier),
                ),
              ],
            ),
          ] else ...[
            const SizedBox(height: 16),
            Text(
              'Connect Strava to auto-import your runs and claim territory from your existing activities.',
              style: GoogleFonts.inter(
                fontSize: 13, color: AppColors.textSecondary, height: 1.5,
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: _StravaButton(
                label: 'Connect with Strava',
                icon: Icons.link_rounded,
                color: stravaOrange,
                isPrimary: true,
                onTap: () => _connectStrava(context, notifier),
              ),
            ),
          ],

          if (strava.error != null) ...[
            const SizedBox(height: 8),
            Text(strava.error!,
              style: GoogleFonts.inter(fontSize: 12, color: AppColors.danger),
            ),
          ],
        ],
      ),
    );
  }

  void _connectStrava(BuildContext context, StravaNotifier notifier) async {
    try {
      final url = await notifier.getAuthUrl();
      if (await canLaunchUrl(Uri.parse(url))) {
        await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Failed to open Strava: $e'),
          backgroundColor: AppColors.danger,
        ));
      }
    }
  }

  void _confirmDisconnect(BuildContext context, StravaNotifier notifier) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: Text('Disconnect Strava?', style: GoogleFonts.inter(
          color: AppColors.textPrimary, fontWeight: FontWeight.w700,
        )),
        content: Text(
          'Your imported activities will keep their territory, but new Strava activities won\'t be synced.',
          style: GoogleFonts.inter(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text('Cancel', style: GoogleFonts.inter(color: AppColors.textMuted)),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              notifier.disconnect();
            },
            child: Text('Disconnect', style: GoogleFonts.inter(color: AppColors.danger)),
          ),
        ],
      ),
    );
  }
}


// ── Reusable UI Components ────────────────────────────────────────────────────

class _GlassCard extends StatelessWidget {
  final Widget child;
  final Color? borderColor;

  const _GlassCard({required this.child, this.borderColor});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.8),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: borderColor ?? AppColors.border.withValues(alpha: 0.5),
          width: 1,
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.2),
            blurRadius: 20,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: child,
    );
  }
}

class _StravaButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback? onTap;
  final bool isPrimary;
  final bool isLoading;

  const _StravaButton({
    required this.label,
    required this.icon,
    required this.color,
    this.onTap,
    this.isPrimary = false,
    this.isLoading = false,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: isPrimary ? color : color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(14),
          border: isPrimary ? null : Border.all(color: color.withValues(alpha: 0.3)),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (isLoading)
              SizedBox(
                width: 16, height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation(
                    isPrimary ? Colors.white : color,
                  ),
                ),
              )
            else
              Icon(icon, size: 18, color: isPrimary ? Colors.white : color),
            const SizedBox(width: 8),
            Text(label, style: GoogleFonts.inter(
              fontSize: 13, fontWeight: FontWeight.w600,
              color: isPrimary ? Colors.white : color,
            )),
          ],
        ),
      ),
    );
  }
}

class _StatsGrid extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: _StatCard(
          icon: Icons.hexagon_rounded, label: 'Cells', value: '—',
          color: AppColors.accent,
        )),
        const SizedBox(width: 12),
        Expanded(child: _StatCard(
          icon: Icons.square_foot_rounded, label: 'km²', value: '—',
          color: const Color(0xFF4FC3F7),
        )),
        const SizedBox(width: 12),
        Expanded(child: _StatCard(
          icon: Icons.directions_run_rounded, label: 'Runs', value: '—',
          color: AppColors.success,
        )),
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  const _StatCard({
    required this.icon, required this.label,
    required this.value, required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.5)),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 24),
          const SizedBox(height: 8),
          Text(value, style: GoogleFonts.inter(
            fontSize: 22, fontWeight: FontWeight.w800,
            color: AppColors.textPrimary,
          )),
          const SizedBox(height: 2),
          Text(label, style: GoogleFonts.inter(
            fontSize: 11, color: AppColors.textMuted,
            letterSpacing: 0.5,
          )),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _InfoRow({required this.icon, required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, size: 18, color: AppColors.textMuted),
        const SizedBox(width: 12),
        Text(label, style: GoogleFonts.inter(
          fontSize: 14, color: AppColors.textSecondary,
        )),
        const Spacer(),
        Text(value, style: GoogleFonts.inter(
          fontSize: 14, fontWeight: FontWeight.w600,
          color: AppColors.textPrimary,
        )),
      ],
    );
  }
}
```

---

## Step 5 — Handle Strava deep link callback

Create `flutter/lib/core/strava/strava_deep_link_handler.dart`:

```dart
// flutter/lib/core/strava/strava_deep_link_handler.dart
import 'package:app_links/app_links.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'strava_provider.dart';

class StravaDeepLinkHandler {
  final AppLinks _appLinks = AppLinks();
  final Ref _ref;

  StravaDeepLinkHandler(this._ref);

  void init() {
    // Handle deep links when app is already running
    _appLinks.uriLinkStream.listen((uri) {
      if (uri.scheme == 'kabja' && uri.host == 'strava-callback') {
        _handleStravaCallback(uri);
      }
    });
  }

  void _handleStravaCallback(Uri uri) {
    final success = uri.queryParameters['success'] == 'true';
    if (success) {
      // Refresh Strava status
      _ref.read(stravaProvider.notifier).loadStatus();
    }
  }
}
```

---

## Step 6 — Add Profile tab to `_HomeShell` in `main.dart`

Update the bottom nav in `flutter/lib/main.dart` to add a 4th tab for Profile:

Find the `_HomeShellState` class and update:

1. Import the profile screen:
```dart
import 'features/profile/profile_screen.dart';
```

2. Add Profile to the pages list:
```dart
final pages = <Widget>[
  const RunScreen(),
  TerritoryMapScreen(userId: userId),
  const CompetitionScreen(),
  const ProfileScreen(),        // ← NEW
];
```

3. Add the nav item:
```dart
_NavItem(
  icon: Icons.person_rounded,
  label: 'Profile',
  isActive: _currentIndex == 3,
  onTap: () => setState(() => _currentIndex = 3),
),
```

---

## Step 7 — Handle Strava WS messages in `territory_map_screen.dart`

Open `flutter/lib/features/map/territory_map_screen.dart`. In the WebSocket listener, add handling for the new message types:

Find the `_ws!.stream.listen` callback. Add these cases:

```dart
if (type == 'strava_sync') {
  // A Strava activity was just imported — refresh territory
  _loadTerritory();
  if (mounted) {
    final name = payload['activity_name'] ?? 'Activity';
    final cells = payload['cells_captured'] ?? 0;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text('🏃 "$name" synced from Strava — $cells cells captured!'),
      backgroundColor: const Color(0xFFFC4C02),
      duration: const Duration(seconds: 3),
    ));
  }
}
if (type == 'strava_sync_status') {
  // Update Strava provider sync status
  ref.read(stravaProvider.notifier).onSyncStatusUpdate(payload);
}
```

---

## Step 8 — Configure deep links

### Android: `flutter/android/app/src/main/AndroidManifest.xml`

Add inside the `<activity>` tag that has the main intent filter:

```xml
<!-- Strava OAuth deep link -->
<intent-filter>
  <action android:name="android.intent.action.VIEW"/>
  <category android:name="android.intent.category.DEFAULT"/>
  <category android:name="android.intent.category.BROWSABLE"/>
  <data android:scheme="kabja" android:host="strava-callback"/>
</intent-filter>
```

### iOS: `flutter/ios/Runner/Info.plist`

Add inside the `<dict>`:

```xml
<key>CFBundleURLTypes</key>
<array>
  <dict>
    <key>CFBundleURLSchemes</key>
    <array>
      <string>kabja</string>
    </array>
    <key>CFBundleURLName</key>
    <string>com.kabja.strava</string>
  </dict>
</array>
```

---

## Step 9 — Initialize deep link handler on app startup

In `flutter/lib/main.dart`, update the `_HomeShellState` to initialize the deep link handler:

```dart
@override
void initState() {
  super.initState();
  // Initialize Strava deep link handler
  StravaDeepLinkHandler(ref).init();
}
```

Add the import:
```dart
import 'core/strava/strava_deep_link_handler.dart';
```

---

## Step 10 — UI/UX Modernization touches

Apply these across all screens for a premium feel:

### Run Screen (`run_screen.dart`)
- Add subtle gradient background (not flat black)
- Use `Shimmer` for loading states
- Add haptic feedback on button taps (`HapticFeedback.mediumImpact()`)
- Animate stat numbers with `TweenAnimationBuilder`

### Competition Screen (`competition_screen.dart`)
- Add glassmorphism cards with `BackdropFilter`
- Countdown timers with pulsing animation
- Prize images with subtle parallax effect

### Territory Map Screen (`territory_map_screen.dart`)
- Add gradient overlay at bottom for leaderboard FAB area
- Pulsing glow effect on runner markers
- Smooth camera animation when centering on user

### General
- All loading states should use `Shimmer` placeholders, not `CircularProgressIndicator`
- All tap targets should have `InkWell` with `splashColor: AppColors.accentGlow`
- All cards should have subtle `BoxShadow` with accent color glow

---

## Smoke test

```bash
# 1. Build and run
flutter pub get
flutter run

# 2. Verify:
# - Profile tab appears in bottom nav
# - Profile screen shows user info + Strava section
# - "Connect with Strava" button opens browser
# - After OAuth, app receives deep link and updates status
# - "Sync Now" button triggers activity import
# - Disconnect button works with confirmation dialog
# - Map screen shows snackbar when Strava activity is auto-imported
```

---

## DO NOT TOUCH

- `backend/` — Backend Engineer and Realtime Engineer own this
- `docker-compose.yml` — Backend Engineer owns this
- `nginx/` — do not touch

---

*Frontend Engineer brief — Strava Integration + UI Modernization — 2026-06-09*
