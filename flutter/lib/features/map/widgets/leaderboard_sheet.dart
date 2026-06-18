import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../../../core/config/app_config.dart';
import '../../../core/theme/app_theme.dart';
import 'package:google_fonts/google_fonts.dart';

class LeaderboardSheet extends StatefulWidget {
  final String token;
  const LeaderboardSheet({super.key, required this.token});

  @override
  State<LeaderboardSheet> createState() => _LeaderboardSheetState();
}

class _LeaderboardSheetState extends State<LeaderboardSheet> {
  List<Map<String, dynamic>> _entries = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/leaderboard'),
        headers: {'Authorization': 'Bearer ${widget.token}'},
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        setState(() {
          _entries = (data['leaderboard'] as List)
              .cast<Map<String, dynamic>>();
          _loading = false;
        });
      }
    } catch (_) {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.6,
      minChildSize: 0.3,
      maxChildSize: 0.85,
      expand: false,
      builder: (_, scrollCtrl) => Column(
        children: [
          const SizedBox(height: 12),
          Container(
            width: 36, height: 4,
            decoration: BoxDecoration(
              color: AppColors.textSecondary.withOpacity(0.4),
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(height: 20),
          Text('LEADERBOARD',
              style: GoogleFonts.bebasNeue(
                  fontSize: 24, color: AppColors.textPrimary, letterSpacing: 2)),
          const SizedBox(height: 8),
          const Divider(color: AppColors.surfaceHigh, height: 1),
          if (_loading)
            const Expanded(child: Center(
                child: CircularProgressIndicator(color: AppColors.accent)))
          else if (_entries.isEmpty)
            const Expanded(child: Center(
                child: Text('No data yet',
                    style: TextStyle(color: AppColors.textSecondary))))
          else
            Expanded(
              child: ListView.builder(
                controller: scrollCtrl,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                itemCount: _entries.length,
                itemBuilder: (_, i) {
                  final e = _entries[i];
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 32,
                          child: Text('${i + 1}',
                              style: GoogleFonts.bebasNeue(
                                  fontSize: 18, color: i < 3
                                      ? AppColors.accent
                                      : AppColors.textSecondary)),
                        ),
                        Expanded(
                          child: Text(e['display_name'] ?? e['username'] ?? '',
                              style: const TextStyle(
                                  color: AppColors.textPrimary, fontSize: 15)),
                        ),
                        Text('${e['km2'] ?? 0} km\u00B2',
                            style: GoogleFonts.bebasNeue(
                                fontSize: 16, color: AppColors.accent)),
                      ],
                    ),
                  );
                },
              ),
            ),
        ],
      ),
    );
  }
}
