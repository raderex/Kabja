import 'package:flutter/material.dart';
import '../../../core/theme/app_theme.dart';

class RunningMarker extends StatefulWidget {
  final bool isOther;
  const RunningMarker({super.key, required this.isOther});

  @override
  State<RunningMarker> createState() => _RunningMarkerState();
}

class _RunningMarkerState extends State<RunningMarker>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _bounce;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 600))
      ..repeat(reverse: true);
    _bounce = Tween<double>(begin: 0, end: -6).animate(
        CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut));
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = widget.isOther ? Colors.blue : AppColors.accent;

    return AnimatedBuilder(
      animation: _bounce,
      builder: (_, __) => Transform.translate(
        offset: Offset(0, _bounce.value),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: widget.isOther ? 28 : 36,
              height: widget.isOther ? 28 : 36,
              decoration: BoxDecoration(
                color: color,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: color.withOpacity(0.5),
                    blurRadius: 8, spreadRadius: 2,
                  )
                ],
              ),
              child: Center(
                child: Text(
                  '\u{1F3C3}',
                  style: TextStyle(fontSize: widget.isOther ? 14 : 18),
                ),
              ),
            ),
            CustomPaint(
              size: const Size(10, 5),
              painter: _TrianglePainter(color: color),
            ),
          ],
        ),
      ),
    );
  }
}

class _TrianglePainter extends CustomPainter {
  final Color color;
  _TrianglePainter({required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = color;
    final path = Path()
      ..moveTo(0, 0)
      ..lineTo(size.width / 2, size.height)
      ..lineTo(size.width, 0)
      ..close();
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(_) => false;
}
