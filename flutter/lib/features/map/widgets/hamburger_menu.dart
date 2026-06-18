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
            onTap: () {},
            child: Container(
              width: 280,
              height: double.infinity,
              color: AppColors.surface,
              child: SafeArea(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
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
