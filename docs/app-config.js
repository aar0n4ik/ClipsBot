// Публичные настройки сайта (без секретов). Client ID / key у площадок не секретные — секреты лежат в GitHub Secrets.
window.APP_CONFIG = {
  tiktokClientKey: "awprgkp1lrrramu9",       // developers.tiktok.com → твоё приложение → Client key
  youtubeClientId: "938822839032-67bp8463osubnrd0hfbbbgij1suoith1.apps.googleusercontent.com",       // console.cloud.google.com → APIs & Services → Credentials → OAuth client ID
  instagramClientId: "1085939634277714",     // developers.facebook.com → приложение → Instagram → Instagram app ID
  // owner и repo определяются из адреса GitHub Pages автоматически. Переопредели, если сайт на своём домене:
  // owner: "your-github-name",
  // repo: "clips",
};

// Для совместимости, если где-то на фронте используется старое имя:
window.CLIPHQ_CONFIG = window.APP_CONFIG;
