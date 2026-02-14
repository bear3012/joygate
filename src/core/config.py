# src/joygate/core/config.py
latency_budget_ms_p95: int = 50

slot_duration_minutes: int = 45
plug_window_minutes: int = 15
leave_grace_minutes: int = 15
grace_slice_minutes: int = 5

wifi_presence_is_absolute: bool = True
wifi_overrides_gps: bool = True
gps_arrival_radius_m: int = 150

presence_revoke_buffer_minutes: int = 3
presence_revoke_distance_threshold_m: int = 500
revoke_observe_minutes: int = 2
approach_distance_delta_m: int = 200

pending_confirmation_minutes: int = 2

off_peak_bonus_multiplier: int = 2
early_release_bonus_minutes: int = 5
bonus_daily_cap: int = 1
