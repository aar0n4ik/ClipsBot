#!/usr/bin/env bash
# ffmpeg, шрифты с кириллицей, TwitchDownloaderCLI (чат), модель лиц.
# Быстро: ничего не качает повторно (кэш в workflow), не зависает (таймауты на каждую загрузку), не трогает apt без нужды.
set -euo pipefail
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
[ -n "${GITHUB_PATH:-}" ] && echo "$BIN_DIR" >> "$GITHUB_PATH"
export PATH="$BIN_DIR:$PATH"

if ! command -v ffmpeg >/dev/null || ! dpkg -s fontconfig >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq ffmpeg fontconfig libfontconfig1 >/dev/null
fi

mkdir -p fonts
get() {  # get URL FILE — с таймаутом, при сбое не валим весь шаг
  [ -s "fonts/$2" ] && return 0
  curl -fsSL --retry 3 --connect-timeout 20 --max-time 180 -o "fonts/$2" "$1" || echo "⚠️ шрифт $2 не скачался"
}
get https://github.com/google/fonts/raw/main/ofl/delagothicone/DelaGothicOne-Regular.ttf DelaGothicOne-Regular.ttf
for f in Montserrat-Black Montserrat-BlackItalic Montserrat-ExtraBold; do
  get "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/$f.ttf" "$f.ttf"
done

if ! command -v TwitchDownloaderCLI >/dev/null; then
  tmp=$(mktemp -d)
  timeout 300 gh release download --repo lay295/TwitchDownloader --pattern "*CLI*Linux-x64*" -D "$tmp"
  unzip -q -o "$tmp"/*.zip -d "$tmp/cli"
  install -m 755 "$tmp/cli/TwitchDownloaderCLI" "$BIN_DIR/TwitchDownloaderCLI"
fi

ffmpeg -version | head -1
ls -la fonts
# модель поиска лица (кадрирование за стримером); без неё работает запасной способ
mkdir -p assets
[ -s assets/face_detection_yunet.onnx ] || curl -fsSL --retry 3 --connect-timeout 20 --max-time 180 -o assets/face_detection_yunet.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
  || echo "⚠️ модель лиц не скачалась — кадрирование пойдёт по запасному способу"
