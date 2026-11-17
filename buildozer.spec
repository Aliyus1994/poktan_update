[app]
title = SIGA BKKBN
package.name = sigabkkbn
package.domain = org.siga
source.dir = .
source.include_exts = py
version = 1.0
requirements = python3,kivy==2.3.0,requests,urllib3,certifi,charset-normalizer,idna
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
p4a.branch = master

[buildozer]
log_level = 2
warn_on_root = 1
