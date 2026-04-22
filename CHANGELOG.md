# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-04-22

### Added
- Sensor platform: dedicated temperature and humidity sensor entities per device
- Humidity attribute exposed on the climate entity
- Dual-setpoint support for heat/cool mode (`target_temperature_high` / `target_temperature_low` and `TARGET_TEMPERATURE_RANGE` feature flag)
- Versioned log prefix (`[vN]`) on all coordinator log messages to confirm new builds are active after a restart
- Startup info log recording `log_version` and `site_id` at integration load time

### Changed
- Coordinator extracted to its own `coordinator.py` module (was previously in `__init__.py`)
- API timeout raised from 10 s to 30 s
- API retry logic: exponential-backoff retries (up to 3×, base delay 60 s) on HTTP 429 rate-limit responses and timeout errors
- Optimistic command cache: sent commands are cached and re-applied over polled device data so the UI reflects changes immediately rather than reverting to stale cloud values
- Cache eviction changed from `updatedAt`-comparison to a 60-second TTL — more reliable when the cloud is slow to propagate updates
- `send_command` now uses a per-device `asyncio.Lock`, ensuring only one API call is in-flight per device at a time; commands that arrive while one is in-flight are held in a last-write-wins pending slot
- Minimum 5-second gap enforced between consecutive sends to the same device
- All setpoints rounded to the nearest 0.5 °C boundary before sending, matching Kumo Cloud's internal precision
- `target_temperature_step` returns `1.0` when the HA UI is set to Fahrenheit (was always `0.5`)
- `hvac_action` logic refined for `autoCool` / `autoHeat` modes with per-mode threshold checks against the correct setpoint
- `async_set_temperature` correctly handles independent high/low setpoints in `HEAT_COOL` mode instead of applying a fixed 2-degree hysteresis
- `HVAC_TO_KUMO_MODE` reverse mapping made explicit to avoid collision with `autoCool` / `autoHeat`

### Fixed
- Syntax error in `async_turn_off` (stray quote character)
- Circular import between `__init__.py` and `climate.py`

## [1.1.0] - 2024-01-02

### Added
- Support for units that report `autoHeat` or `autoCool` operation modes
- HVACMode.HEAT_COOL now activates when these modes are reported

## [1.0.0] - 2024-01-01

### Added
- Initial release of Mitsubishi Comfort integration
- Climate control support for Mitsubishi Electric systems via Kumo Cloud API
- Config flow for easy setup
- Multi-zone support
- Automatic token refresh
- Device capability detection
- Support for temperature, HVAC modes, fan speeds, and air direction
- Real-time temperature and humidity monitoring

### Features
- Climate entity with full Home Assistant integration
- Automatic discovery of zones within selected site
- Configurable update intervals
- Error handling and retry logic
- Support for multiple HVAC modes (heat, cool, dry, fan, auto)
- Device-specific feature detection 