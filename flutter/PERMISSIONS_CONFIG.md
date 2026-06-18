# Flutter Platform Permission Configuration
# Kathmandu Bus Tracker — App Store Compliance

# ═══════════════════════════════════════════════════════
#  iOS — Info.plist keys (Runner/Info.plist)
# ═══════════════════════════════════════════════════════
#
# Add these keys to ios/Runner/Info.plist:

# <key>NSLocationWhenInUseUsageDescription</key>
# <string>KTM Bus Tracker uses your location to show your bus on the map and calculate arrival time.</string>
#
# <key>NSLocationAlwaysAndWhenInUseUsageDescription</key>
# <string>Driver mode requires background location so parents can track the bus even when the app is closed.</string>
#
# <key>NSLocationAlwaysUsageDescription</key>
# <string>Driver mode requires always-on location for continuous bus tracking.</string>
#
# <key>UIBackgroundModes</key>
# <array>
#   <string>location</string>
#   <string>fetch</string>
# </array>

# ═══════════════════════════════════════════════════════
#  Android — AndroidManifest.xml
# ═══════════════════════════════════════════════════════
#
# Add to android/app/src/main/AndroidManifest.xml <manifest> section:

# <!-- Standard location -->
# <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION"/>
# <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION"/>
#
# <!-- Background location (required for Driver role; triggers Play Store review) -->
# <uses-permission android:name="android.permission.ACCESS_BACKGROUND_LOCATION"/>
#
# <!-- Prevent CPU sleep during tracking -->
# <uses-permission android:name="android.permission.WAKE_LOCK"/>
#
# <!-- Keep network during background -->
# <uses-permission android:name="android.permission.INTERNET"/>
# <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
#
# <!-- Foreground service (required for Android 12+ background location) -->
# <uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
# <uses-permission android:name="android.permission.FOREGROUND_SERVICE_LOCATION"/>
#
# Inside <application>:
# <service
#   android:name="com.baseflow.geolocator.service.GeolocationService"
#   android:foregroundServiceType="location"
#   android:exported="false"/>

# ═══════════════════════════════════════════════════════
#  App Store / Play Store Review Notes
# ═══════════════════════════════════════════════════════
#
# Apple App Store — Background Location:
#   • Requires "Core Location" capability in Xcode Signing & Capabilities
#   • App Review will ask: "Why does this need background location?"
#   • Answer: "This is a school bus tracking app. The driver role requires
#     continuous background location so parents can see the bus moving in
#     real time, even when the phone is locked."
#   • Provide Privacy Policy URL: https://yourdomain.com/privacy
#   • Provide Support URL:        https://yourdomain.com/support
#
# Google Play Store — Background Location:
#   • Must complete "Prominent Disclosure" form in Play Console
#   • Policy: https://support.google.com/googleplay/android-developer/answer/9799150
#   • Declare ONLY the foreground (Driver) app uses background location.
#     The Parent app does NOT require it.
#   • Two separate apps (or flavors) is cleaner for Play Store policy.

# ═══════════════════════════════════════════════════════
#  Flutter flavors — Driver vs Parent
# ═══════════════════════════════════════════════════════
#
# Use Flutter flavors to produce two distinct APKs/IPAs:
#
#   flutter build apk --flavor parent --target lib/main_parent.dart
#   flutter build apk --flavor driver --target lib/main_driver.dart
#
# This avoids requesting background location permission in the parent app.
# android/app/build.gradle flavors config:
#
# flavorDimensions "app"
# productFlavors {
#   parent {
#     dimension "app"
#     applicationId "com.ktmbustrack.parent"
#     resValue "string", "app_name", "KTM School Bus"
#   }
#   driver {
#     dimension "app"
#     applicationId "com.ktmbustrack.driver"
#     resValue "string", "app_name", "KTM Bus Driver"
#   }
# }
