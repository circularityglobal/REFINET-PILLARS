[app]

# REFInet Pillar — Android Package Configuration
# Built with Buildozer (python-for-android backend)

title = REFInet Pillar
package.name = pillar
package.domain = io.refinet
version = 0.3.0

# Source
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt,json,dapp

# Application entry point
# main.py is the Kivy UI; service.py runs the daemon
entrypoint = main.py

# All .py files + data files are included via source.include_exts above.
# Do NOT set source.include_patterns — it overrides include_exts and would
# exclude the copied pillar packages (core/, crypto/, gopherroot/, etc.).

# Python-for-android requirements
# Core: kivy for UI, pyjnius for Android service API
# Pillar deps: cryptography, argon2-cffi
# Optional: websockets (for browser bridge)
requirements = python3,kivy,pyjnius,android,cryptography,argon2-cffi,websockets

# Android permissions
# INTERNET: TCP server + mesh networking
# FOREGROUND_SERVICE: keep pillar running in background
# ACCESS_NETWORK_STATE: detect connectivity for mesh
# WAKE_LOCK: prevent CPU sleep while serving
android.permissions = INTERNET,FOREGROUND_SERVICE,ACCESS_NETWORK_STATE,WAKE_LOCK

# Android API levels
android.minapi = 26
android.api = 34
android.ndk = 25b

# Architecture — build for ARM64 (modern Android devices)
android.archs = arm64-v8a

# Orientation
orientation = portrait

# Fullscreen off (use system status bar)
fullscreen = 0

# Android service — runs pillar daemon in background
services = Pillarservice:service.py:foreground

# Icon and presplash (will use defaults if not provided)
# icon.filename = %(source.dir)s/icon.png
# presplash.filename = %(source.dir)s/presplash.png

# Build configuration
android.release_artifact = apk
android.accept_sdk_license = True
android.skip_update = False

# Gradle / Java
android.gradle_dependencies =
android.add_jars =
android.add_aars =

# Include pillar source packages in the APK
# These get copied into the app's private storage
p4a.extra_args = --copy-libs

# Log level for build debugging
log_level = 2

# Build directory
build_dir = ./build
bin_dir = ./bin

[buildozer]
log_level = 2
warn_on_root = 1
