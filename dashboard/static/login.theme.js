// Apply the theme the dashboard saved, before first paint (this script is loaded in <head>).
try {
  var saved = localStorage.getItem('marke-theme');
  if (saved === 'light' || saved === 'dark') document.documentElement.dataset.theme = saved;
} catch (e) { /* storage unavailable: follow the system theme */ }
