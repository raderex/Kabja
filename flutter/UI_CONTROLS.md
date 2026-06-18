# Flutter UI Controls Documentation
## KTM Bus Tracker — Parent & Driver Apps

---

## The Button (UI Control)

### My Location Button

**Official Name:** My Location button

**Function:** When pressed, it centers the map camera on the user's current GPS coordinates.

**Developer Property:** In the Google Maps SDK (Android/iOS), it is enabled via the `myLocationButton` property (e.g., `mapView.settings.myLocationButton = true`).

**Icon Style:** It typically looks like a target or crosshair (a circle with a dot in the center). In Material Design icon sets, this is often named `my_location`.

---

### Implementation Details

#### Parent App (KTM School Bus)
- **Visibility:** The My Location button appears when the parent is viewing the map
- **Behavior:** 
  - Shows as a small Floating Action Button (FAB) with a target/crosshair icon
  - Positioned in the bottom-right corner of the map
  - Only visible when the parent has disconnected from the bus or after the trip ends
- **Code Location:** [lib/features/map/map_screen.dart](lib/features/map/map_screen.dart#L243)
- **Functionality:** Tapping it re-centers the map to show the parent's current GPS location

#### Driver App (KTM Bus Driver)
- **Visibility:** The My Location button appears when the driver is on the map screen
- **Behavior:**
  - Shows as a small Floating Action Button (FAB) with a target/crosshair icon
  - Positioned in the bottom-right corner of the map
  - Only visible when the driver is not actively broadcasting location
- **Code Location:** [lib/features/map/map_screen.dart](lib/features/map/map_screen.dart#L243)
- **Functionality:** Tapping it re-centers the map to show the driver's current GPS location

---

### Technical Specifications

**Flutter Implementation:**
```dart
FloatingActionButton.small(
  heroTag: 'recenter',
  backgroundColor: AppColors.accent,
  foregroundColor: Colors.white,
  elevation: 4,
  onPressed: _recenter,
  child: const Icon(Icons.my_location_rounded),
)
```

**Icon Used:** `Icons.my_location_rounded` (Material Design Icons)

**Button Type:** Small Floating Action Button (FAB)

**Styling:**
- **Background Color:** Primary accent color (`AppColors.accent`)
- **Icon Color:** White (`Colors.white`)
- **Elevation:** 4dp (provides shadow depth)
- **Size:** Small FAB variant

**Callback Method:** `_recenter()` — Moves the map controller to the user's current GPS coordinates

---

### User Flow

#### Parent App Flow
1. Parent opens the KTM School Bus app
2. Parent enters a code to connect to a bus
3. Map loads and centers on the bus location
4. Parent can tap the **My Location button** to center the map on their own GPS location
5. Map animates to parent's position

#### Driver App Flow
1. Driver opens the KTM Bus Driver app
2. Driver taps "Start Sharing" to begin broadcasting their location
3. Map loads and centers on the driver's location
4. Driver can tap the **My Location button** to re-center on their position if the map has been panned
5. Map animates back to driver's position

---

### Conditional Visibility

The My Location button is conditionally displayed based on app state:

```dart
if (_showRecenter || (isDriver && broadcast.driverPosition != null && !_followBus))
  // Button is visible
```

**Parent App:** Button shows when `_showRecenter` is true (when map has been panned)

**Driver App:** Button shows when driver is actively broadcasting and map is not in "follow mode"
