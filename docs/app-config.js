// Публичные настройки сайта (без секретов). Client ID / key у площадок не секретные — секреты лежат в GitHub Secrets.
window.CLIPHQ_CONFIG = {
  tiktokClientKey: "CHANGE_ME",       // developers.tiktok.com → твоё приложение → Client key
  youtubeClientId: "CHANGE_ME",       // console.cloud.google.com → APIs & Services → Credentials → OAuth client ID
  instagramClientId: "CHANGE_ME",     // developers.facebook.com → приложение → Instagram → Instagram app ID
  // owner и repo определяются из адреса GitHub Pages автоматически. Переопредели, если сайт на своём домене:
  // owner: "your-github-name",
  // repo: "clips",
};
