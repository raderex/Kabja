# AGENT 1 — Flutter UI Architect (v3.1 — Full Feature Pass)

## Agent Profile
- **Role**: Senior Flutter/Dart UI Engineer
- **Codename**: Agent 1 — Flutter UI Architect
- **Scope**: All Flutter/Dart code in `/home/raderex/Documents/bustrack/flutter`
- **Flutter SDK**: `/home/raderex/flutter/bin/flutter`
- **Run analyze**: `cd flutter && /home/raderex/flutter/bin/flutter analyze --no-pub`

## Context (READ FIRST)
The app is installed and running on Waydroid. Two flavors:
- **`com.ktmbustrack.parent`** → "KTM School Bus" (Parent app)
- **`com.ktmbustrack.driver`** → "KTM Bus Driver" (Driver app)

The app names are already correct in `build.gradle.kts`. The bug causing **both to show as "KTM School Bus"** is that the `android:label` in `AndroidManifest.xml` uses `@string/app_name`, and the `resValue` in Gradle uses `app_name`, but there is **no `res/values/strings.xml` in `main/`** — this means `@string/app_name` falls back to a hardcoded string somewhere. **Fix is T1 below.**

## Issues Found (from live testing on Waydroid)
1. ❌ **Both apps show "KTM School Bus"** — driver app label wrong
2. ❌ **Zoom out (−) button does not work** — `mapController.move()` called outside `build()` with stale controller ref
3. ❌ **No "my location" pin** — driver cannot see their own position on the map
4. ❌ **No auto-center on driver's own GPS** — map stays on Kathmandu center on load
5. ❌ **Parent: "Disconnect" button missing** — once connected, no way to disconnect
6. ❌ **Parent: no trip-ended overlay** — when driver stops, nothing happens in UI
7. ❌ **Share code not copyable/shareable** — driver cannot copy/share code to WhatsApp
8. ❌ **Driver: no location permission prompt** on first launch (before hitting Start)
9. ❌ **Trip timer missing** — driver can't see how long the trip has been running
10. ❌ **Settings drawer: App Version still says v2.0.0** — should be v3.0.0
11. ❌ **No "My Location" re-center for driver** (only shows when tracking bus, not for driver's own position)

---

## Task List

### T1: Fix App Label — Driver App Shows Wrong Name
**Priority**: 🔴 CRITICAL
**Root cause**: `android:label="@string/app_name"` in `AndroidManifest.xml`, but there is no `res/values/strings.xml`. The `resValue` in `build.gradle.kts` generates the string at build time — this *should* work, but Waydroid's APM cache may have stale metadata.

**Fix — create `res/values/strings.xml` as fallback**:
```xml
<!-- android/app/src/main/res/values/strings.xml -->
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <!-- This is overridden per-flavor by build.gradle.kts resValue -->
    <string name="app_name">KTM Bus Track</string>
</resources>
```

File path: `flutter/android/app/src/main/res/values/strings.xml`

The `build.gradle.kts` already has:
```kotlin
create("parent") { resValue("string", "app_name", "KTM School Bus") }
create("driver") { resValue("string", "app_name", "KTM Bus Driver") }
```
This is correct — just create the fallback strings.xml so the build succeeds cleanly.

---

### T2: Fix Zoom-Out Button
**Priority**: 🔴 CRITICAL
**Root cause**: `mapController.move()` is called correctly but the `cameraConstraint` in `MapOptions` may be preventing zoom-out by clamping zoom. Also, `minZoom: 10` may conflict with UI bounds.

**Fix in `map_screen.dart`**:
```dart
// Remove the cameraConstraint entirely (it's causing the zoom-out block):
// DELETE these lines:
//   cameraConstraint: CameraConstraint.contain(
//     bounds: LatLngBounds(...)
//   ),

// Change minZoom to allow more zoom out:
minZoom: 6,   // was 10 — too restrictive
maxZoom: 18,
```

**Also fix zoom buttons** to clamp properly in `zoom_controls.dart`:
```dart
// In _ZoomButton for zoom out:
onTap: () {
  final current = mapController.camera.zoom;
  if (current > 6) {
    mapController.move(mapController.camera.center, current - 1);
  }
},
// In _ZoomButton for zoom in:
onTap: () {
  final current = mapController.camera.zoom;
  if (current < 18) {
    mapController.move(mapController.camera.center, current + 1);
  }
},
```

---

### T3: Driver — "My Location" Blue Dot + Auto-Center
**Priority**: 🔴 CRITICAL

The driver needs to see their own position on the map at all times — like Google Maps' blue pulsing dot with accuracy ring. This should appear **even before broadcasting starts**.

**Step 1: Add a `driverLocationProvider`** in `broadcast_provider.dart`:
Add `LatLng? driverPosition` and `double? driverAccuracy` to `BroadcastState`:
```dart
class BroadcastState {
  // ... existing fields ...
  final LatLng? driverPosition;    // ADD
  final double? driverHeading;     // ADD — compass bearing
  final double? driverAccuracy;    // ADD — accuracy ring radius in meters
}
```

Add a **passive location watcher** that starts on `BroadcastNotifier` init (not only when broadcasting):
```dart
// In BroadcastNotifier constructor:
BroadcastNotifier(this._ref) : super(const BroadcastState()) {
  _startPassiveLocationWatch(); // Always watch driver location
}

StreamSubscription<Position>? _passiveLocationSub;

void _startPassiveLocationWatch() async {
  // Check permission first — if denied, do nothing (don't ask yet)
  final status = await Permission.location.status;
  if (!status.isGranted) return;

  _passiveLocationSub = Geolocator.getPositionStream(
    locationSettings: const LocationSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 3,
    ),
  ).listen((pos) {
    state = state.copyWith(
      driverPosition: LatLng(pos.latitude, pos.longitude),
      driverAccuracy: pos.accuracy,
      driverHeading: pos.heading,
      speed: state.isBroadcasting ? pos.speed * 3.6 : null,
    );
  });
}
```

**Step 2: Add "My Location" marker layer to `map_screen.dart`**:
```dart
// In the FlutterMap children list, add after TileLayer:
MarkerLayer(markers: [
  // Driver's own blue dot
  if (isDriver && broadcast.driverPosition != null)
    Marker(
      point: broadcast.driverPosition!,
      width: 80,
      height: 80,
      child: _MyLocationDot(
        accuracy: broadcast.driverAccuracy ?? 20,
        heading: broadcast.driverHeading ?? 0,
      ),
    ),
]),
```

**Step 3: Create `_MyLocationDot` widget** (can be in `map_screen.dart` or a new `my_location_dot.dart`):
```dart
class _MyLocationDot extends StatefulWidget {
  const _MyLocationDot({required this.accuracy, required this.heading});
  final double accuracy;
  final double heading;

  @override
  State<_MyLocationDot> createState() => _MyLocationDotState();
}

class _MyLocationDotState extends State<_MyLocationDot>
    with SingleTickerProviderStateMixin {
  late AnimationController _pulse;

  @override
  void initState() {
    super.initState();
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat();
  }

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      alignment: Alignment.center,
      children: [
        // Pulsing accuracy ring
        AnimatedBuilder(
          animation: _pulse,
          builder: (_, __) => Transform.scale(
            scale: 0.5 + _pulse.value * 0.5,
            child: Opacity(
              opacity: 1.0 - _pulse.value,
              child: Container(
                width: 60,
                height: 60,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: const Color(0xFF4285F4).withValues(alpha: 0.2),
                  border: Border.all(
                    color: const Color(0xFF4285F4).withValues(alpha: 0.3),
                    width: 1,
                  ),
                ),
              ),
            ),
          ),
        ),
        // White ring
        Container(
          width: 20,
          height: 20,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: Colors.white,
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.3),
                blurRadius: 8,
              ),
            ],
          ),
        ),
        // Blue dot
        Container(
          width: 14,
          height: 14,
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            color: Color(0xFF4285F4),
          ),
        ),
      ],
    );
  }
}
```

**Step 4: Auto-center map on driver's own location** on first position fix:
```dart
// In _MapScreenState, add a flag:
bool _didInitialDriverCenter = false;

// In build(), watch broadcast:
// When driver gets their first position, fly to it:
ref.listen<BroadcastState>(broadcastProvider, (prev, next) {
  if (isDriver && !_didInitialDriverCenter && next.driverPosition != null) {
    _didInitialDriverCenter = true;
    _mapController.move(next.driverPosition!, 16.0);
  }
  // Keep following driver's position while NOT panned away:
  if (isDriver && _followBus && next.driverPosition != null) {
    _mapController.move(next.driverPosition!, _mapController.camera.zoom);
  }
});
```

**Step 5: Driver re-center FAB** — update `_recenter()` to handle driver mode:
```dart
void _recenter() {
  setState(() {
    _followBus = true;
    _showRecenter = false;
  });
  final broadcast = ref.read(broadcastProvider);
  final tracking = ref.read(trackingProvider);
  final auth = ref.read(authProvider);

  if (auth.role == 'driver' && broadcast.driverPosition != null) {
    _mapController.move(broadcast.driverPosition!, 16.0);
  } else if (tracking.busPosition != null) {
    _mapController.move(tracking.busPosition!, 15.0);
  }
}
```

**Step 6: Show re-center FAB for driver** (currently only shows for parent with bus position):
```dart
// Show recenter if driver has panned away from their own dot:
if (_showRecenter || (isDriver && broadcast.driverPosition != null && !_followBus))
```

---

### T4: Driver — Request Location Permission on App Start (Not on Button Press)
**Priority**: 🔴 CRITICAL

Currently, location permission is requested only when "Start Broadcasting" is tapped. This is bad UX — the driver sees an empty map with no dot, then taps a button, then gets a permission dialog.

**Fix**: Request location on app init (in `BroadcastNotifier` constructor OR in `MapScreen.initState` for driver flavor).

In `map_screen.dart` `initState`:
```dart
@override
void initState() {
  super.initState();
  _mapController = MapController();
  // Request location early for driver (permission + passive watch)
  WidgetsBinding.instance.addPostFrameCallback((_) {
    final auth = ref.read(authProvider);
    if (auth.role == 'driver') {
      ref.read(broadcastProvider.notifier).ensureLocationPermission();
    }
  });
}
```

In `BroadcastNotifier`, add:
```dart
Future<void> ensureLocationPermission() async {
  var status = await Permission.location.status;
  if (!status.isGranted) {
    status = await Permission.location.request();
  }
  if (status.isGranted) {
    _startPassiveLocationWatch();
  }
  state = state.copyWith(permissionGranted: status.isGranted);
}
```

---

### T5: Driver — Share Code Card: Copy + WhatsApp Share
**Priority**: 🔴 CRITICAL

Currently the tracking code is shown but there's no way to share it. Add copy-to-clipboard and share sheet.

**In `broadcast_controls.dart`**, update the share code card section:
```dart
// Add import:
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

// Replace current code card Row with:
Row(
  children: [
    Expanded(
      child: GestureDetector(
        onTap: () {
          Clipboard.setData(ClipboardData(text: state.trackingCode ?? ''));
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Code copied to clipboard!'),
              duration: Duration(seconds: 2),
            ),
          );
        },
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppColors.surfaceHigh,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: AppColors.success.withValues(alpha: 0.25),
            ),
          ),
          child: Column(
            children: [
              Text(
                state.trackingCode ?? '',
                style: GoogleFonts.robotoMono(
                  fontSize: 28,
                  fontWeight: FontWeight.w800,
                  color: AppColors.success,
                  letterSpacing: 4,
                ),
              ),
              const SizedBox(height: 4),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.copy_rounded, size: 12, color: AppColors.textSecondary),
                  const SizedBox(width: 4),
                  Text(
                    'Tap to copy',
                    style: GoogleFonts.inter(
                      fontSize: 11,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    ),
    const SizedBox(width: 10),
    // WhatsApp / Share button
    GestureDetector(
      onTap: () {
        final code = state.trackingCode ?? '';
        SharePlus.instance.share(
          ShareParams(
            text: 'Track your bus live! Enter code: $code in KTM Bus Track app.',
          ),
        );
      },
      child: Container(
        width: 56,
        height: 86,
        decoration: BoxDecoration(
          color: const Color(0xFF25D366).withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: const Color(0xFF25D366).withValues(alpha: 0.3),
          ),
        ),
        child: const Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.share_rounded, color: Color(0xFF25D366), size: 22),
            SizedBox(height: 4),
            Text(
              'Share',
              style: TextStyle(
                fontSize: 10,
                color: Color(0xFF25D366),
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    ),
  ],
),
```

**Add `share_plus` to `pubspec.yaml`** if not present:
```yaml
dependencies:
  share_plus: ^10.1.4
```

---

### T6: Driver — Live Trip Timer
**Priority**: 🟡 MEDIUM

Add a trip duration timer to the broadcast stats panel.

**In `BroadcastState`**: `trackingStartedAt` is already present.

**In `broadcast_controls.dart`**, add a 4th stat chip for trip time:
```dart
// Add a StreamBuilder or use a stateful widget for live time:
_TripTimerChip(startedAt: state.trackingStartedAt),

// New widget:
class _TripTimerChip extends StatefulWidget {
  const _TripTimerChip({required this.startedAt});
  final DateTime? startedAt;

  @override
  State<_TripTimerChip> createState() => _TripTimerChipState();
}

class _TripTimerChipState extends State<_TripTimerChip> {
  late Timer _timer;
  String _elapsed = '00:00';

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (widget.startedAt != null) {
        final diff = DateTime.now().difference(widget.startedAt!);
        final h = diff.inHours;
        final m = diff.inMinutes % 60;
        final s = diff.inSeconds % 60;
        setState(() {
          _elapsed = h > 0
              ? '${h.toString().padLeft(2,'0')}:${m.toString().padLeft(2,'0')}:${s.toString().padLeft(2,'0')}'
              : '${m.toString().padLeft(2,'0')}:${s.toString().padLeft(2,'0')}';
        });
      }
    });
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _StatChip(
      icon: Icons.timer_rounded,
      label: 'Time',
      value: _elapsed,
    );
  }
}
```

Update the Row to use 4 stats in a Wrap or 2x2 grid:
```dart
Wrap(
  spacing: 8,
  runSpacing: 8,
  children: [
    SizedBox(
      width: (MediaQuery.of(context).size.width - 56) / 2,
      child: _StatChip(icon: Icons.send_rounded, label: 'Pings', value: '${state.pingCount}'),
    ),
    SizedBox(
      width: (MediaQuery.of(context).size.width - 56) / 2,
      child: _StatChip(
        icon: Icons.speed_rounded,
        label: 'Speed',
        value: state.speed != null ? '${state.speed!.toStringAsFixed(0)} km/h' : '—',
      ),
    ),
    SizedBox(
      width: (MediaQuery.of(context).size.width - 56) / 2,
      child: _StatChip(icon: Icons.people_rounded, label: 'Parents', value: '${state.parentsConnected}'),
    ),
    SizedBox(
      width: (MediaQuery.of(context).size.width - 56) / 2,
      child: _TripTimerChip(startedAt: state.trackingStartedAt),
    ),
  ],
),
```

---

### T7: Parent — Disconnect Button + Trip Ended Overlay
**Priority**: 🔴 CRITICAL

**A) Add Disconnect button to `tracking_bottom_sheet.dart`**:
```dart
// At the bottom of the ListView, add:
const SizedBox(height: 16),
SizedBox(
  width: double.infinity,
  height: 44,
  child: OutlinedButton.icon(
    onPressed: () {
      ref.read(trackingProvider.notifier).disconnect();
    },
    icon: const Icon(Icons.link_off_rounded, size: 16),
    label: const Text('Disconnect'),
    style: OutlinedButton.styleFrom(
      foregroundColor: const Color(0xFFCF6679),
      side: const BorderSide(color: Color(0xFFCF6679)),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
      ),
    ),
  ),
),
```

Make `TrackingBottomSheet` a `ConsumerWidget` (needs ref for disconnect):
```dart
class TrackingBottomSheet extends ConsumerWidget {
  const TrackingBottomSheet({
    super.key,
    required this.state,
    required this.scrollController,
  });
  // ...
  @override
  Widget build(BuildContext context, WidgetRef ref) { ... }
}
```

**B) Add "Trip Ended" overlay in `map_screen.dart`**:

Add a `tripEnded` flag to `TrackingState` (in `tracking_provider.dart`):
```dart
final bool tripEnded;  // True when driver sent "ended" message
```

In `_connectWs` inside `tracking_provider.dart`, when `type == 'ended'`:
```dart
case 'ended':
  state = state.copyWith(
    wsState: WsConnectionState.disconnected,
    tripEnded: true,   // Don't auto-disconnect — show overlay first
  );
```

In `map_screen.dart`, add the overlay:
```dart
// Show "Trip Ended" overlay when driver stops
if (!isDriver && tracking.tripEnded)
  Positioned.fill(
    child: Container(
      color: Colors.black.withValues(alpha: 0.7),
      child: Center(
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 32),
          padding: const EdgeInsets.all(28),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(24),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.directions_bus_rounded, size: 52, color: AppColors.accent),
              const SizedBox(height: 16),
              Text(
                'Trip Ended',
                style: GoogleFonts.inter(
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textPrimary,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'The driver has stopped broadcasting.',
                textAlign: TextAlign.center,
                style: GoogleFonts.inter(
                  fontSize: 14,
                  color: AppColors.textSecondary,
                ),
              ),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: () {
                  ref.read(trackingProvider.notifier).disconnect();
                },
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.accent,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
                child: const Text('OK'),
              ),
            ],
          ),
        ),
      ),
    ),
  ),
```

---

### T8: Fix `TrackingState` — Add Missing `tripEnded` + `copyWith` Updates
**Priority**: 🔴 CRITICAL (required for T7)
**File**: `lib/core/tracking/tracking_provider.dart`

Add `tripEnded` field:
```dart
class TrackingState {
  const TrackingState({
    // ... existing ...
    this.tripEnded = false,  // ADD
  });

  // ... existing fields ...
  final bool tripEnded;  // ADD

  TrackingState copyWith({
    // ... existing ...
    bool? tripEnded,  // ADD
  }) => TrackingState(
    // ... existing ...
    tripEnded: tripEnded ?? this.tripEnded,  // ADD
  );
}
```

In `disconnect()`, reset it:
```dart
void disconnect() {
  _wsManager?.dispose();
  _wsManager = null;
  state = const TrackingState();  // Already resets everything
  SharedPreferences.getInstance().then((p) => p.remove(_prefsKey));
}
```

---

### T9: Settings Drawer — Version + Driver-Specific Info
**Priority**: 🟡 MEDIUM
**File**: `lib/features/map/widgets/settings_drawer.dart`

1. Change version to `v3.0.0`
2. For driver, show broadcast state info instead of tracking info
3. Add a "My Bus" tile for driver showing their bus number when broadcasting

```dart
// Replace the version tile:
_DrawerTile(
  icon: Icons.info_rounded,
  title: 'App Version',
  subtitle: 'v3.0.0',
),

// Add driver-specific section (if isDriver):
if (auth.role == 'driver') ...[
  Consumer(builder: (ctx, ref, _) {
    final broadcast = ref.watch(broadcastProvider);
    return _DrawerTile(
      icon: Icons.directions_bus_rounded,
      title: 'Bus Number',
      subtitle: broadcast.busNumber ?? 'Not broadcasting',
    );
  }),
  Consumer(builder: (ctx, ref, _) {
    final broadcast = ref.watch(broadcastProvider);
    return _DrawerTile(
      icon: Icons.share_rounded,
      title: 'Active Code',
      subtitle: broadcast.trackingCode ?? 'None',
    );
  }),
],
```

---

### T10: `pubspec.yaml` — Add Missing Dependencies
**Priority**: 🔴 CRITICAL (required for T5)
**File**: `flutter/pubspec.yaml`

Check if `share_plus` is already there. If not, add:
```yaml
dependencies:
  share_plus: ^10.1.4
```

Then run: `/home/raderex/flutter/bin/flutter pub get`

---

## Verification Checklist

```bash
cd /home/raderex/Documents/bustrack/flutter

# 1. Get dependencies
/home/raderex/flutter/bin/flutter pub get

# 2. Static analysis — must be 0 ERRORS (infos/warnings ok)
/home/raderex/flutter/bin/flutter analyze --no-pub

# 3. Build parent APK
/home/raderex/flutter/bin/flutter build apk --debug --flavor parent \
  --dart-define-from-file=config/env.waydroid.json

# 4. Build driver APK
/home/raderex/flutter/bin/flutter build apk --debug --flavor driver \
  --dart-define-from-file=config/env.waydroid.json

# 5. Install both
waydroid app install build/app/outputs/flutter-apk/app-parent-debug.apk
waydroid app install build/app/outputs/flutter-apk/app-driver-debug.apk

# 6. Verify app names
waydroid app list | grep ktm
```

## Success Criteria
- ✅ Driver app shows "KTM Bus Driver" (not "KTM School Bus")
- ✅ Zoom out (−) button works
- ✅ Blue pulsing dot shows driver's location on map immediately
- ✅ Map auto-centers on driver's GPS location on first fix
- ✅ Driver: re-center FAB works for own position
- ✅ Driver: location permission requested on map load (not on button tap)
- ✅ Driver: share code card has Copy and Share buttons
- ✅ Driver: trip timer counts up in broadcast panel
- ✅ Parent: Disconnect button visible in bottom sheet
- ✅ Parent: "Trip Ended" overlay appears when driver stops
- ✅ Settings drawer shows v3.0.0
- ✅ 0 flutter analyze errors
- ✅ Both APK flavors build successfully
