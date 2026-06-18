import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../features/map/map_screen.dart';
import '../../features/auth/login_screen.dart';
import '../../features/auth/register_screen.dart';
import '../../features/run/run_screen.dart';
import '../../features/competition/competition_screen.dart';
import '../../features/profile/profile_screen.dart';
import '../auth/auth_provider.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final auth = ref.watch(authProvider);

  return GoRouter(
    initialLocation: '/map',
    redirect: (context, state) {
      final authRequired = ['/run', '/profile'];
      if (authRequired.contains(state.matchedLocation) && !auth.isLoggedIn) {
        return '/login?from=${state.matchedLocation}';
      }
      return null;
    },
    routes: [
      GoRoute(path: '/map',         builder: (_, __) => const MapScreen()),
      GoRoute(path: '/run',          builder: (_, __) => const RunScreen()),
      GoRoute(path: '/competition',  builder: (_, __) => const CompetitionScreen()),
      GoRoute(path: '/profile',      builder: (_, __) => const ProfileScreen()),
      GoRoute(path: '/login',        builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/register',     builder: (_, __) => const RegisterScreen()),
    ],
  );
});
