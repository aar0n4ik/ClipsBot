// Публичные настройки сайта (без секретов). Client ID / key у площадок не секретные — секреты лежат в GitHub Secrets.
window.CLIPHQ_CONFIG = {
  tiktokClientKey: "awprgkp1lrrramu9",       // developers.tiktok.com → твоё приложение → Client key
  youtubeClientId: "938822839032-67bp8463osubnrd0hfbbbgij1suoith1.apps.googleusercontent.com",       // console.cloud.google.com → APIs & Services → Credentials → OAuth client ID
  instagramClientId: "2148866103174523",     // developers.facebook.com → приложение → Instagram → Instagram app ID
  // owner и repo определяются из адреса GitHub Pages автоматически. Переопредели, если сайт на своём домене:
  // owner: "your-github-name",
  // repo: "clips",
};
