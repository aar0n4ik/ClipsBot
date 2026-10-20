#!/usr/bin/env bash
# ffmpeg, шрифты с кириллицей, TwitchDownloaderCLI (чат)
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg fontconfig libfontconfig1 >/dev/null
mkdir -p fonts
get() { [ -s "fonts/$2" ] || curl -fsSL --retry 3 -o "fonts/$2" "$1" || echo "⚠️ шрифт $2 не скачался"; }
get https://github.com/google/fonts/raw/main/ofl/delagothicone/DelaGothicOne-Regular.ttf DelaGothicOne-Regular.ttf
for f in Montserrat-Black Montserrat-BlackItalic Montserrat-ExtraBold; do
  get "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/$f.ttf" "$f.ttf"
done
if ! command -v TwitchDownloaderCLI >/dev/null; then
  tmp=$(mktemp -d)
  gh release download --repo lay295/TwitchDownloader --pattern "*CLI*Linux-x64*" -D "$tmp"
  unzip -q -o "$tmp"/*.zip -d "$tmp/cli"
  sudo install -m 755 "$tmp/cli/TwitchDownloaderCLI" /usr/local/bin/TwitchDownloaderCLI
fi
ffmpeg -version | head -1
ls -la fonts
# модель поиска лица (кадрирование за стримером); без неё работает запасной способ
mkdir -p assets
[ -s assets/face_detection_yunet.onnx ] || curl -fsSL --retry 3 -o assets/face_detection_yunet.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
  || echo "⚠️ модель лиц не скачалась — кадрирование пойдёт по запасному способу"
