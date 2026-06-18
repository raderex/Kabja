import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import '../../core/auth/auth_provider.dart';
import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';
import 'package:google_fonts/google_fonts.dart';

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});
  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _displayCtrl = TextEditingController();
  bool _loading = false;
  String? _error;

  Future<void> _register() async {
    setState(() { _loading = true; _error = null; });
    try {
      final res = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/auth/register'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'username': _userCtrl.text.trim(),
          'password': _passCtrl.text,
          'display_name': _displayCtrl.text.trim().isEmpty
              ? _userCtrl.text.trim()
              : _displayCtrl.text.trim(),
        }),
      );
      if (res.statusCode == 200 || res.statusCode == 201) {
        final data = jsonDecode(res.body);
        await ref.read(authProvider.notifier).setAuth(
          token: data['access_token'],
          userId: data['user_id'],
          username: data['username'],
          displayName: data['display_name'] ?? data['username'],
        );
        if (mounted) context.go('/map');
      } else {
        final body = jsonDecode(res.body);
        setState(() => _error = body['detail'] ?? 'Registration failed');
      }
    } catch (e) {
      setState(() => _error = 'Connection error. Is the server running?');
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Spacer(),
              Text('CREATE ACCOUNT', style: Theme.of(context).textTheme.displayMedium),
              const SizedBox(height: 8),
              Text('Join the territory battle.',
                  style: GoogleFonts.inter(
                      color: AppColors.textSecondary, fontSize: 13)),
              const SizedBox(height: 40),
              _Field(ctrl: _userCtrl, label: 'Username', icon: Icons.person_outline),
              const SizedBox(height: 14),
              _Field(ctrl: _displayCtrl, label: 'Display Name (optional)',
                  icon: Icons.badge),
              const SizedBox(height: 14),
              _Field(ctrl: _passCtrl, label: 'Password',
                  icon: Icons.lock_outline, obscure: true),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: AppColors.danger, fontSize: 13)),
              ],
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: _loading ? null : _register,
                child: _loading
                    ? const SizedBox(width: 20, height: 20,
                        child: CircularProgressIndicator(
                            color: Colors.black, strokeWidth: 2))
                    : const Text('REGISTER'),
              ),
              const SizedBox(height: 14),
              Center(
                child: TextButton(
                  onPressed: () => context.go('/login'),
                  child: Text('Already have an account? Login',
                      style: TextStyle(color: AppColors.accent, fontSize: 13)),
                ),
              ),
              const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  final TextEditingController ctrl;
  final String label;
  final IconData icon;
  final bool obscure;
  const _Field({required this.ctrl, required this.label,
      required this.icon, this.obscure = false});

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: ctrl,
      obscureText: obscure,
      style: const TextStyle(color: AppColors.textPrimary),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: AppColors.textSecondary),
        prefixIcon: Icon(icon, color: AppColors.textSecondary, size: 20),
        filled: true,
        fillColor: AppColors.surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AppColors.accent, width: 1.5),
        ),
      ),
    );
  }
}
