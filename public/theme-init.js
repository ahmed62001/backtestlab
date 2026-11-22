(function () {
  try {
    var t = localStorage.getItem('bl_theme');
    if (t !== 'light' && t !== 'dark') {
      t =
        window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light';
    }
    if (t === 'dark') document.documentElement.classList.add('dark');
    var l = localStorage.getItem('bl_lang');
    if (l !== 'ar' && l !== 'en') l = 'ar';
    document.documentElement.lang = l;
    document.documentElement.dir = l === 'ar' ? 'rtl' : 'ltr';
  } catch (e) {
    document.documentElement.lang = 'ar';
    document.documentElement.dir = 'rtl';
  }
})();
