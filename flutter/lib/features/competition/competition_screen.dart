import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import '../../core/auth/auth_provider.dart';
import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';
import 'package:google_fonts/google_fonts.dart';

class CompetitionScreen extends ConsumerStatefulWidget {
  const CompetitionScreen({super.key});
  @override
  ConsumerState<CompetitionScreen> createState() => _CompetitionScreenState();
}

class _CompetitionScreenState extends ConsumerState<CompetitionScreen> {
  List<Map<String, dynamic>> _competitions = [];
  bool _loading = true;
  Timer? _tick;
  Duration _countdown = Duration.zero;
  int _currentPrizeIndex = 0;
  final _pageCtrl = PageController();

  @override
  void initState() {
    super.initState();
    _load();
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_countdown.inSeconds > 0) {
        setState(() => _countdown = _countdown - const Duration(seconds: 1));
      }
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    _pageCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final auth = ref.read(authProvider);
    try {
      final res = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/competitions'),
        headers: {'Authorization': 'Bearer ${auth.token}'},
      );
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        final list = (data['competitions'] as List)
            .cast<Map<String, dynamic>>();
        setState(() {
          _competitions = list;
          _loading = false;
          if (list.isNotEmpty) {
            final endsAt = DateTime.parse(
                list[0]['ends_at'] ?? list[0]['end_time'] ?? '');
            _countdown = endsAt.difference(DateTime.now());
            if (_countdown.isNegative) _countdown = Duration.zero;
          }
        });
      }
    } catch (_) {
      setState(() => _loading = false);
    }
  }

  String _formatCountdown(Duration d) {
    final days = d.inDays;
    final h = (d.inHours % 24).toString().padLeft(2, '0');
    final m = (d.inMinutes % 60).toString().padLeft(2, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    return '${days}d ${h}h ${m}m ${s}s';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: Text('COMPETITIONS',
            style: GoogleFonts.bebasNeue(
                fontSize: 22, color: AppColors.textPrimary, letterSpacing: 2)),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: AppColors.accent))
          : _competitions.isEmpty
              ? const Center(
                  child: Text('No active competitions',
                      style: TextStyle(color: AppColors.textSecondary)))
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: _competitions.length,
                  itemBuilder: (_, i) {
                    final comp = _competitions[i];
                    final prizes = (comp['prizes'] as List?)
                            ?.cast<Map<String, dynamic>>() ??
                        [];
                    final territoryKm2 = (comp['your_territory_km2'] ??
                        comp['territory_km2'] ??
                        0).toDouble();

                    return Container(
                      margin: const EdgeInsets.only(bottom: 20),
                      decoration: BoxDecoration(
                        color: AppColors.surface,
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          ClipRRect(
                            borderRadius: const BorderRadius.vertical(
                                top: Radius.circular(16)),
                            child: SizedBox(
                              height: 200,
                              child: prizes.isEmpty
                                  ? Container(
                                      color: AppColors.surfaceHigh,
                                      child: const Center(
                                          child: Icon(Icons.emoji_events_outlined,
                                              color: AppColors.accent, size: 48)))
                                  : PageView.builder(
                                      controller: _pageCtrl,
                                      onPageChanged: (idx) =>
                                          setState(() => _currentPrizeIndex = idx),
                                      itemCount: prizes.length,
                                      itemBuilder: (_, pi) {
                                        final prize = prizes[pi];
                                        return Stack(
                                          fit: StackFit.expand,
                                          children: [
                                            if (prize['image_url'] != null)
                                              Image.network(
                                                prize['image_url'],
                                                fit: BoxFit.cover,
                                                errorBuilder: (_, __, ___) =>
                                                    _prizePlaceholder(prize),
                                              )
                                            else
                                              _prizePlaceholder(prize),
                                            Positioned(
                                              bottom: 0, left: 0, right: 0,
                                              child: Container(
                                                padding: const EdgeInsets.all(12),
                                                decoration: BoxDecoration(
                                                  gradient: LinearGradient(
                                                    begin: Alignment.topCenter,
                                                    end: Alignment.bottomCenter,
                                                    colors: [
                                                      Colors.transparent,
                                                      Colors.black.withOpacity(0.8),
                                                    ],
                                                  ),
                                                ),
                                                child: Text(
                                                  prize['name'] ?? 'Prize',
                                                  style: GoogleFonts.bebasNeue(
                                                      fontSize: 24,
                                                      color: Colors.white,
                                                      letterSpacing: 1),
                                                ),
                                              ),
                                            ),
                                          ],
                                        );
                                      },
                                    ),
                            ),
                          ),
                          if (prizes.length > 1)
                            Center(
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: List.generate(
                                  prizes.length,
                                  (pi) => Container(
                                    margin: const EdgeInsets.symmetric(
                                        horizontal: 3, vertical: 10),
                                    width: pi == _currentPrizeIndex ? 20 : 8,
                                    height: 8,
                                    decoration: BoxDecoration(
                                      color: pi == _currentPrizeIndex
                                          ? AppColors.accent
                                          : AppColors.textSecondary.withOpacity(0.3),
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text('ENDING IN',
                                        style: GoogleFonts.inter(
                                            fontSize: 10,
                                            color: AppColors.textSecondary,
                                            letterSpacing: 2)),
                                    const SizedBox(height: 4),
                                    Text(_formatCountdown(_countdown),
                                        style: GoogleFonts.bebasNeue(
                                            fontSize: 22,
                                            color: AppColors.accent)),
                                  ],
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 14, vertical: 8),
                                  decoration: BoxDecoration(
                                    color: AppColors.accent.withOpacity(0.15),
                                    borderRadius: BorderRadius.circular(20),
                                    border: Border.all(
                                        color: AppColors.accent.withOpacity(0.3)),
                                  ),
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      const Icon(Icons.hexagon,
                                          color: AppColors.accent, size: 16),
                                      const SizedBox(width: 6),
                                      Text('${territoryKm2.toStringAsFixed(1)} km\u00B2',
                                          style: GoogleFonts.bebasNeue(
                                              fontSize: 16,
                                              color: AppColors.accent)),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
    );
  }

  Widget _prizePlaceholder(Map<String, dynamic> prize) {
    return Container(
      color: AppColors.surfaceHigh,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.card_giftcard,
                color: AppColors.accent, size: 48),
            const SizedBox(height: 8),
            Text(prize['name'] ?? 'Prize',
                style: GoogleFonts.bebasNeue(
                    fontSize: 20, color: AppColors.textSecondary)),
          ],
        ),
      ),
    );
  }
}
