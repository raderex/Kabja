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
