# CLAUDE CODE (Kimi K2.6) — UI Implementation Task

**Status**: NOT STARTED (claims completed but no actual changes made)  
**Deadline**: ASAP  
**Workspace**: `/home/raderex/Documents/bustrack/flutter`

---

## CURRENT STATE (BROKEN)
- Role selector buttons still visible on login screen
- No "Start Sharing" button on driver screen
- Home screen still shows routes (not "Join Ride" UI)

---

## TASK C1: Remove Role Selector + Auto-Detect Role

**File**: `flutter/lib/features/auth/login_screen.dart`

**What to do**:
1. Delete the `_RoleSelector` widget (currently at line 283 and class definition at line 373)
2. Delete lines with `_role = 'parent'` and role selector in the form
3. After successful login, the app should check the JWT role and auto-navigate:
   - If role == "driver" → go to driver_screen
   - If role == "parent" → go to home_screen
4. Remove the `_role` variable completely

**Current broken code** (lines 280-286):
```dart
                            // Role selector
                            _RoleSelector(
                              selected: _role,
                              onChanged: (r) => setState(() => _role = r),
                            ),
```

**Action**: Delete that entire block

---

## TASK C2: Add "Start Sharing" Button to Driver Screen

**File**: `flutter/lib/features/driver/driver_screen.dart`

**What to do**:
1. Find the big red button (currently "Start Trip" or similar)
2. Change button text to "Start Sharing"
3. On tap, call `POST /api/share` endpoint
4. Display the returned `share_code` prominently (e.g., "Share Code: ABC123D")
5. Show "Sharing to X parents" counter
6. Start broadcasting GPS via WebSocket to `/ws/share/{share_code}`

**Expected response from POST /api/share**:
```json
{
  "share_code": "ABC123D",
  "share_url": "ktmbustrack://share/ABC123D",
  "expires_at": "2026-05-28T10:30:00Z"
}
```

---

## TASK C3: Add "Join Ride" UI to Parent Home Screen

**File**: `flutter/lib/features/home/home_screen.dart`

**What to do**:
1. Replace the route list with a "Join a Ride" card
2. Add text input field with placeholder "Enter Share Code (e.g., ABC123D)"
3. On submit:
   - Call `POST /api/share/{share_code}` to validate
   - If success: connect to WebSocket `/ws/share/{share_code}`
   - If error: show error message
4. Once joined, show driver's live location on map

**Expected response from POST /api/share/{code}**:
```json
{
  "status": "joined",
  "share_code": "ABC123D",
  "driver_id": "raderex",
  "parents_connected": 2
}
```

---

## VERIFICATION

After completing all tasks:`
```bash
cd flutter && flutter analyze --no-pub
# Target: 0 errors (warnings OK)
```

Then rebuild APK:
```bash
flutter build apk --debug --flavor parent --dart-define-from-file=config/env.waydroid.json
flutter build apk --debug --flavor driver --dart-define-from-file=config/env.waydroid.json
```

---

## SUCCESS CRITERIA

✅ Login screen has NO role selector buttons  
✅ User logs in → auto-routed to correct screen (no manual choice)  
✅ Driver sees "Start Sharing" button  
✅ Parent sees "Join Ride" input field  
✅ No compilation errors
